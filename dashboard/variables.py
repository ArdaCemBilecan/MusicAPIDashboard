"""Dashboard filtreleri (değişkenler).

Bir dashboard'un üst kısmındaki filtreler (ör. Ülke, Sanatçı) birer değişkendir.
Widget'lar bir parametreyi sabit değer yerine bir değişkene bağlayabilir:

    şablon parametresi : {"country": {"$var": "country"}}
    özel sorgu filtresi: {"field": "home_country", "op": "eq", "value": {"$var": "country"}}
    SQL                : WHERE home_country = {{country}}

Widget verisi istenirken tarayıcı o anki değerleri gönderir ({"country": "Germany"})
ve bağlı alanlar burada gerçek değerlerle değiştirilir.
"""
import copy

from .templates import TEMPLATES, ParamError

VAR_TYPES = {"country": "Ülke", "artist": "Sanatçı", "tag": "Tür"}


def _is_ref(value):
    return isinstance(value, dict) and "$var" in value


def _lookup(ref, values):
    v = values.get(ref["$var"])
    if isinstance(v, list):
        v = [x for x in v if x not in (None, "")]
        return v or None
    return v if v not in (None, "") else None


def resolve(source, values):
    """Kaynağın bağlı alanlarını değişken değerleriyle doldurulmuş bir kopyasını döner."""
    values = values or {}
    src = copy.deepcopy(source)

    if src.get("type") == "template":
        tpl = TEMPLATES.get(src.get("template")) or {"params": []}
        labels = {p["name"]: p["label"] for p in tpl["params"]}
        params = src.get("params") or {}
        for name, value in list(params.items()):
            if not _is_ref(value):
                continue
            v = _lookup(value, values)
            if v is None:
                raise ParamError(f"'{labels.get(name, name)}' için üstteki filtreden bir değer seçin")
            # Şablon parametreleri tek değer alır: çoklu seçimde ilk değer kullanılır
            params[name] = v[0] if isinstance(v, list) else v
        src["params"] = params

    elif src.get("type") == "custom":
        spec = src.get("spec") or {}
        kept = []
        for f in spec.get("filters") or []:
            if _is_ref(f.get("value")):
                v = _lookup(f["value"], values)
                if v is None:          # filtrede seçim yok = bu koşulu uygulama ("Tümü")
                    continue
                f = {**f, "value": v}
            kept.append(f)
        spec["filters"] = kept
        for part in ("num", "den"):
            cond = (spec.get(part) or {}).get("cond") or {}
            if _is_ref(cond.get("value")):
                v = _lookup(cond["value"], values)
                cond["value"] = v if v is not None else ""
        if _is_ref(spec.get("sort_series")):
            v = _lookup(spec["sort_series"], values)
            spec["sort_series"] = (v[0] if isinstance(v, list) else v) or ""
        src["spec"] = spec

    elif src.get("type") == "sql":
        src.setdefault("spec", {})["vars"] = values

    return src
