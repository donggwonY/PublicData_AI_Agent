"""상가정보 분기 파일: 한도 확인 → 다운로드 → 대구만 추출 → 원본 삭제. CAPTCHA 요구 시 중단."""
import sys, os, subprocess, zipfile, json, io, csv, time
S = sys.argv[1]; OUT = os.path.join(S, 'dl_aux_20261108', 'sangga'); TMP = os.path.join(S, 'dl_aux_20261108', 'sangga_tmp')
os.makedirs(OUT, exist_ok=True); os.makedirs(TMP, exist_ok=True)
JAR = os.path.join(S, 'web_ld', 'sg_cookie.txt'); UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
PAGE = 'https://www.data.go.kr/data/15083033/fileData.do'
def curl(*a): return subprocess.run(['curl', '-s', '-L', '-c', JAR, '-b', JAR, '-A', UA, '-e', PAGE, *a], capture_output=True)
curl(PAGE, '-o', os.devnull)
log = open(os.path.join(OUT, 'log.tsv'), 'a', encoding='utf-8')
for line in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sg_list.tsv'), encoding='utf-8'):
    q, fid = line.split()
    dst = os.path.join(OUT, f'sangga_daegu_{q}.csv')
    if os.path.exists(dst): continue
    chk = curl('-X', 'POST', '-d', f'atchFileId={fid}&fileDetailSn=1', 'https://www.data.go.kr/cmm/cmm/check-limit.json').stdout.decode()
    if json.loads(chk or '{}').get('needCaptcha', True):
        print(q, 'CAPTCHA 요구 또는 한도 확인 실패 → 중단', chk, flush=True); break
    raw = os.path.join(TMP, f'{q}.bin')
    r = curl('-o', raw, '-w', '%{http_code} %{size_download}', f'https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId={fid}&fileDetailSn=1')
    size = os.path.getsize(raw) if os.path.exists(raw) else 0
    kept, src = 0, ''
    try:
        if zipfile.is_zipfile(raw):
            z = zipfile.ZipFile(raw)
            try:
                for i in z.infolist():
                    n = i.filename
                    if not (i.flag_bits & 0x800):
                        try: n = n.encode('cp437').decode('cp949')
                        except Exception: pass
                    if '대구' in n and n.lower().endswith('.csv'):
                        with z.open(i) as f_in, open(dst, 'wb') as f_out:
                            while True:
                                b = f_in.read(1 << 20)
                                if not b: break
                                f_out.write(b)
                        src = n; kept = os.path.getsize(dst); break
                if not kept:   # 대구 파일이 따로 없으면 전국 CSV 에서 행 필터
                    big = [i for i in z.infolist() if i.filename.lower().endswith('.csv')]
                    src = 'filtered:' + ','.join(i.filename for i in big)
                    with open(dst, 'w', encoding='utf-8', newline='') as f_out:
                        for i in big:
                            raw_bytes = z.open(i)
                            for enc in ('utf-8-sig', 'cp949'):
                                try:
                                    txt = io.TextIOWrapper(z.open(i), encoding=enc, newline='')
                                    rd = csv.reader(txt); hdr = next(rd); w = csv.writer(f_out)
                                    if kept == 0: w.writerow(hdr)
                                    for row in rd:
                                        if any(c == '대구광역시' for c in row[:20]): w.writerow(row); kept += 1
                                    break
                                except UnicodeDecodeError: continue
            finally:
                z.close()
        else:
            src = 'not-zip'
            with open(raw, 'rb') as f: head = f.read(300)
            print(q, 'zip 아님', head[:120], flush=True)
    finally:
        if os.path.exists(raw): os.remove(raw)
    msg = f'{q}\t{fid}\tdownload={r.stdout.decode()}\traw_bytes={size}\tkept={kept}\tsrc={src}'
    print(msg, flush=True); log.write(msg + '\n'); log.flush()
    time.sleep(5)
print('DONE', flush=True)
