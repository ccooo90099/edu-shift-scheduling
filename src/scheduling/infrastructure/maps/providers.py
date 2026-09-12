"""地图服务客户端 —— 地址转经纬度、两点驾车时间与里程。

只在管理侧跑一次，结果落成 CSV；排班本身完全离线，不依赖网络也不需要 key。

两个供应商，按需要的精度选：

    osm （默认，免 key）  Nominatim 地理编码 + OSRM 路径规划，都是开源公共服务。
                          返回 WGS-84。国内 POI 覆盖不如商业地图，商场/门店名
                          经常查不到，建议在地址列填街道级地址。公共服务有速率
                          限制（约 1 次/秒），30 个中心跑一次没问题。

    amap（需要 key）      高德。国内 POI 覆盖好得多，返回 GCJ-02 火星坐标。
                          精度要求高、或者 OSM 查不到时用它。

两家坐标系不同，差 300–700 米。centers.csv 带「坐标系」列记录来源，
engine/coords.py 内部统一折算到 WGS-84，所以混着用也不会算错。
"""
import json
import time
import urllib.parse
import urllib.request

from ...domain.model.venue import Datum

AMAP_GEOCODE = "https://restapi.amap.com/v3/geocode/geo"
AMAP_DISTANCE = "https://restapi.amap.com/v3/distance"
NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
OSRM_TABLE = "https://router.project-osrm.org/table/v1/driving"

# Nominatim 要求可识别的 UA；HTTP 请求头只能使用 Latin-1，中文会在发送前报错。
USER_AGENT = "edu-shift-scheduling/0.1 (one-time batch geocoding)"


class MapError(Exception):
    """地图服务返回了不能用的结果。message 可直接显示给用户。"""


def _get(url, params, timeout=30):
    query = urllib.parse.urlencode(params)
    full = "%s?%s" % (url, query) if query else url
    request = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise MapError("地图服务返回 HTTP %s" % e.code)
    except urllib.error.URLError as e:
        raise MapError("连不上地图服务：%s" % e.reason)
    except (ValueError, TimeoutError) as e:
        raise MapError("地图服务响应无法解析：%s" % e)


class AMap:
    """高德。免费版有 QPS 限制，所以每次调用之间留了间隔。"""

    name = "amap"
    datum = Datum.GCJ02
    needs_key = True

    def __init__(self, key, city="深圳", pause=0.25, fetch=_get):
        self.key = key
        self.city = city
        self.pause = pause
        self.fetch = fetch          # 注入点：测试时换成假的，不打真网络

    def _call(self, url, params):
        params = dict(params, key=self.key, output="JSON")
        data = self.fetch(url, params)
        if str(data.get("status")) != "1":
            raise MapError("高德返回错误：%s（infocode %s）"
                           % (data.get("info", "未知"), data.get("infocode", "-")))
        if self.pause:
            time.sleep(self.pause)
        return data

    def geocode(self, address):
        """地址 → (经度, 纬度)。查不到返回 None，让调用方决定怎么处理。"""
        data = self._call(AMAP_GEOCODE, {"address": address, "city": self.city})
        items = data.get("geocodes") or []
        if not items:
            return None
        location = items[0].get("location") or ""
        if "," not in location:
            return None
        lon, lat = location.split(",", 1)
        return float(lon), float(lat)

    def driving(self, origins, destination):
        """一对多驾车测距。

        origins 是 [(经度, 纬度), ...]，destination 是 (经度, 纬度)。
        返回与 origins 等长的 [(分钟, 公里), ...]；个别点算不出来时该位置是 None。
        高德单次最多 100 个起点。
        """
        if len(origins) > 100:
            raise MapError("高德单次最多 100 个起点，收到 %d 个" % len(origins))
        data = self._call(AMAP_DISTANCE, {
            "origins": "|".join("%.6f,%.6f" % p for p in origins),
            "destination": "%.6f,%.6f" % destination,
            "type": 1,                      # 1 = 驾车
        })

        # 结果按 origin_id 回填，不能假定顺序
        out = [None] * len(origins)
        for row in data.get("results") or []:
            try:
                index = int(row.get("origin_id", 0)) - 1
                minutes = float(row["duration"]) / 60.0
                km = float(row["distance"]) / 1000.0
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= index < len(out):
                out[index] = (minutes, km)
        return out


class OSM:
    """Nominatim + OSRM，都不要 key。

    公共服务有速率限制，所以每次调用之间默认停 1.1 秒（Nominatim 条款要求 ≤1 次/秒）。
    OSRM 的 table 接口一次就能出整个矩阵，比逐点调用省得多。
    """

    name = "osm"
    datum = Datum.WGS84
    needs_key = False

    def __init__(self, key=None, city="深圳", pause=1.1, fetch=_get):
        self.city = city
        self.pause = pause
        self.fetch = fetch

    def _wait(self):
        if self.pause:
            time.sleep(self.pause)

    def geocode(self, address):
        self.last_geocode = None
        data = self.fetch(NOMINATIM_SEARCH, {
            "q": address, "format": "json", "limit": 1,
            "countrycodes": "cn", "accept-language": "zh-CN",
            "addressdetails": 1,
        })
        self._wait()
        if not isinstance(data, list) or not data:
            return None
        try:
            point = float(data[0]["lon"]), float(data[0]["lat"])
        except (KeyError, TypeError, ValueError):
            return None
        self.last_geocode = data[0]
        return point

    def matrix(self, points):
        """一次算出所有两两组合。返回 (分钟矩阵, 公里矩阵)，算不出来的格子是 None。"""
        if len(points) > 100:
            raise MapError("OSRM 公共服务单次最多 100 个点，收到 %d 个" % len(points))
        path = ";".join("%.6f,%.6f" % p for p in points)
        data = self.fetch("%s/%s" % (OSRM_TABLE, path),
                          {"annotations": "duration,distance"})
        self._wait()
        if data.get("code") != "Ok":
            raise MapError("OSRM 返回错误：%s" % data.get("message", data.get("code", "未知")))

        size = len(points)
        durations = data.get("durations") or []
        distances = data.get("distances") or []

        def cell(matrix, i, j, scale):
            try:
                value = matrix[i][j]
            except (IndexError, TypeError):
                return None
            return None if value is None else float(value) / scale

        minutes = [[cell(durations, i, j, 60.0) for j in range(size)] for i in range(size)]
        km = [[cell(distances, i, j, 1000.0) for j in range(size)] for i in range(size)]
        return minutes, km


PROVIDERS = {"osm": OSM, "amap": AMap}


def make(provider, key=None, **kw):
    if provider not in PROVIDERS:
        raise MapError("不支持的地图服务：%s（可选 %s）"
                       % (provider, "、".join(sorted(PROVIDERS))))
    cls = PROVIDERS[provider]
    if getattr(cls, "needs_key", False) and not key:
        raise MapError("%s 需要 --key" % provider)
    return cls(key, **kw)
