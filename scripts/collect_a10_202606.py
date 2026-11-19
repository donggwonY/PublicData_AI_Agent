"""Stream the public June 2026 archive, retaining only its Daegu CSV."""

import hashlib
import json
import struct
import urllib.parse
import urllib.request
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "data/raw"
QUERY = urllib.parse.urlencode({"atchFileId": "FILE_000000007754450", "fileDetailSn": "1"})
URL = "https://www.data.go.kr/cmm/cmm/fileDownload.do?" + QUERY + "&dataNm=20260630"


def main():
    request = urllib.request.Request(
        "https://www.data.go.kr/cmm/cmm/check-limit.json", data=QUERY.encode()
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if json.load(response).get("needCaptcha"):
            raise RuntimeError("Official download requires CAPTCHA")
    with urllib.request.urlopen(URL, timeout=60) as response:
        while True:
            header = response.read(30)
            if len(header) != 30:
                raise ValueError("Daegu CSV not found in archive")
            signature, version, flags, method, time, date, crc, size, raw_size, name_size, extra_size = struct.unpack(
                "<IHHHHHIIIHH", header
            )
            if signature != 0x04034B50 or flags & 9 or method not in (0, 8):
                raise ValueError("Unsupported archive entry")
            name_bytes = response.read(name_size)
            name = name_bytes.decode("utf-8" if flags & 2048 else "cp949")
            response.read(extra_size)
            keep = "대구" in name and name.endswith("_202606.csv")
            print(name, size, flush=True)
            inflater = zlib.decompressobj(-15) if method == 8 else None
            chunks = []
            remaining = size
            while remaining:
                block = response.read(min(1024 * 1024, remaining))
                if not block:
                    raise ValueError("Truncated download")
                remaining -= len(block)
                if keep:
                    chunks.append(inflater.decompress(block) if inflater else block)
            if keep:
                if inflater:
                    chunks.append(inflater.flush())
                data = b"".join(chunks)
                if len(data) != raw_size or zlib.crc32(data) != crc:
                    raise ValueError("CSV length or archive CRC mismatch")
                target = ROOT / "a08/daegu_stores_202606.csv"
                target.write_bytes(data)
                manifest = {
                    "source_page": "https://www.data.go.kr/data/15083033/fileData.do",
                    "history_detail_pk": "uddi:b3094bc9-8756-4ecc-9141-9144b98a531e",
                    "download_url": URL, "entry": name,
                    "reference_date": "2026-06-30", "retrieved_date": "2026-11-19",
                    "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                }
                (ROOT / "a10/202606_source.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print("Retained", target.name, len(data), "bytes", flush=True)
                return


if __name__ == "__main__":
    main()
