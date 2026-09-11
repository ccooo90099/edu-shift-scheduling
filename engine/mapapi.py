"""地图服务客户端 —— 地址转经纬度、两点驾车时间与里程。

只在管理侧跑一次，结果落成 CSV；排班本身完全离线，不依赖网络也不需要 key。
默认接高德（深圳覆盖好、免费额度够用）。换供应商只要再写一个 Provider 子类。
"""
import json
import time
import urllib.parse
import urllib.request

AMAP_GEOCODE = "https://restapi.amap.com/v3/geocode/geo"
AMAP_DISTANCE = "https://restapi.amap.com/v3/distance"


class MapError(Exception):
    """地图服务返回了不能用的结果。message 可直接显示给用户。"""


def _get(url, params, timeout=20):
    query = urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen("%s?%s" % (url, query), timeout=timeout) as resp:
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


PROVIDERS = {"amap": AMap}


def make(provider, key, **kw):
    if provider not in PROVIDERS:
        raise MapError("不支持的地图服务：%s（可选 %s）"
                       % (provider, "、".join(sorted(PROVIDERS))))
    return PROVIDERS[provider](key, **kw)
