"""Kandil: kuyruk.json'daki sıradaki Reels'i Instagram'a yayınlar (GitHub Actions, her gün 19:00 TR).

Kuyruğu Ahmet'in bilgisayarındaki gece üretimi doldurur (yayin.py): video bu deponun release'ine konur,
kuyruk.json'a {etiket, video_url, caption, tarih, durum: bekliyor} yazılır. Bu betik günde en fazla bir
video yayınlar, sonucu (durum: paylasildi | hata) kuyruk.json'a yazar; iş akışı dosyayı commit eder.
Hata olursa TEKRAR DENEMEZ (çift yayın riski): durum 'hata' olur, Ahmet karar verir.

Gizli değerler (Settings -> Secrets -> Actions): IG_TOKEN, IG_ID, IG_API (isteğe bağlı).
Token asla yazdırılmaz.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

API = os.environ.get("IG_API") or "https://graph.facebook.com"
SURUM = "v27.0"
TR = timezone(timedelta(hours=3))
BEKLEME_SN = 900


class Hata(Exception):
    pass


def istek(yontem, url, **kw):
    try:
        r = requests.request(yontem, url, timeout=120, **kw)
    except requests.RequestException as e:
        raise Hata(f"Ağ hatası: {type(e).__name__}")
    try:
        veri = r.json()
    except ValueError:
        veri = {}
    if r.status_code >= 400 or (isinstance(veri, dict) and "error" in veri):
        h = veri.get("error", {}) if isinstance(veri, dict) else {}
        raise Hata(f"HTTP {r.status_code}: {h.get('message', r.text[:200])} [kod {h.get('code')}]")
    return veri


def yayinla(v, tok, uid):
    c = istek("POST", f"{API}/{SURUM}/{uid}/media", data={
        "media_type": "REELS", "video_url": v["video_url"], "caption": v["caption"],
        "share_to_feed": "true", "is_ai_generated": "true", "access_token": tok})
    cid = c.get("id")
    if not cid:
        raise Hata("Container kimliği gelmedi.")
    print(f"  container {cid}; Instagram videoyu indirip işliyor…")
    bas = time.time()
    while True:
        s = istek("GET", f"{API}/{SURUM}/{cid}", params={"fields": "status_code,status", "access_token": tok})
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") in ("ERROR", "EXPIRED"):
            raise Hata(f"İşlenemedi: {s.get('status_code')} {s.get('status', '')}")
        if time.time() - bas > BEKLEME_SN:
            raise Hata(f"İşleme {BEKLEME_SN} sn'de bitmedi (container {cid}).")
        time.sleep(10)
    p = istek("POST", f"{API}/{SURUM}/{uid}/media_publish", data={"creation_id": cid, "access_token": tok})
    mid = p.get("id")
    if not mid:
        raise Hata("Yayın kimliği gelmedi.")
    link = None
    try:
        m = istek("GET", f"{API}/{SURUM}/{mid}", params={"fields": "permalink,is_ai_generated", "access_token": tok})
        link = m.get("permalink")
        print(f"  is_ai_generated: {m.get('is_ai_generated')}")
    except Hata:
        pass
    return mid, link


def main():
    kuru = os.environ.get("KURU", "").lower() == "true"
    with open("kuyruk.json", encoding="utf-8") as f:
        k = json.load(f)
    simdi = datetime.now(TR)
    bugun = simdi.date().isoformat()
    # GitHub zamanlanmış görevi saatlerce gecikebiliyor (25.11: 8 saat): gece yayın olmasın.
    # Elle tetikleme (workflow_dispatch) her saatte çalışır.
    if os.environ.get("OLAY") == "schedule" and not 18 <= simdi.hour <= 23:
        print(f"{simdi:%H:%M} TR: zamanlanmış görev yayın saatleri (18:00-23:59) dışında geç çalıştı, yayın yok.")
        return 0
    videolar = k.setdefault("videolar", [])
    # Günde bir akşam yayını: zamanlanmış görev, bu akşam (18:00 sonrası) yayın yapıldıysa çıkar.
    # Elle tetikleme (workflow_dispatch) bu kontrole takılmaz; her çalıştırmada en fazla bir video yayınlar.
    aksam = f"{bugun}T18"
    if os.environ.get("OLAY") == "schedule" and any(
            v.get("durum") == "paylasildi" and str(v.get("zaman", "")) >= aksam and str(v.get("zaman", "")).startswith(bugun)
            for v in videolar):
        print(f"{bugun}: bu akşam zaten bir video yayınlandı.")
        return 0
    aday = sorted((v for v in videolar if v.get("durum") == "bekliyor" and v.get("tarih", "") <= bugun),
                  key=lambda v: (v.get("tarih", ""), v.get("sira", 0)))
    if not aday:
        print(f"{bugun}: yayınlanacak video yok.")
        return 0
    v = aday[0]
    print(f"Sıradaki: {v['etiket']} ({v.get('tarih')})")
    if kuru:
        print("[kuru] yayınlanmadı.")
        return 0
    tok, uid = os.environ.get("IG_TOKEN"), os.environ.get("IG_ID")
    if not tok or not uid:
        print("HATA: IG_TOKEN / IG_ID gizli değerleri yok.")
        return 1
    try:
        mid, link = yayinla(v, tok, uid)
        v.update({"durum": "paylasildi", "media_id": mid, "permalink": link, "zaman": datetime.now(TR).isoformat(timespec="minutes")})
        print(f"Yayınlandı: {link or mid}")
        kod = 0
    except Hata as e:
        v.update({"durum": "hata", "hata": str(e), "zaman": datetime.now(TR).isoformat(timespec="minutes")})
        print(f"HATA (tekrar denenmedi): {e}")
        kod = 1
    with open("kuyruk.json", "w", encoding="utf-8") as f:
        json.dump(k, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return kod


if __name__ == "__main__":
    sys.exit(main())
