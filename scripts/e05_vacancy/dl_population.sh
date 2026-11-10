S=$1; D=$S/dl_aux_20261108/population; W=$S/web_ld; UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64)"; J=$W/jm.txt
rm -f $D/test.csv
for y in $(seq 2011 2026); do for half in 1 2; do
  if [ $half = 1 ]; then a=01; b=06; else a=07; b=12; fi
  if [ $y = 2026 ] && [ $half = 2 ]; then b=10; fi
  out=$D/pop_${y}${a}_${y}${b}.csv
  [ -s $out ] && continue
  curl -s -c $J -b $J -A "$UA" -e https://jumin.mois.go.kr/ageStatMonth.do -X POST -o $out.tmp -w "$y$a-$y$b %{http_code} %{size_download}\n" \
   --data "sltOrgType=1&sltOrgLvl1=2700000000&sltOrgLvl2=A&gender=gender&sum=sum&sltUndefType=&searchYearStart=$y&searchMonthStart=$a&searchYearEnd=$y&searchMonthEnd=$b&sltOrderType=1&sltOrderValue=ASC&sltArgTypes=10&sltArgTypeA=0&sltArgTypeB=100&category=month" \
   "https://jumin.mois.go.kr/downloadCsvAge.do?searchYearMonth=month&xlsStats=3"
  # 대구 행만 남김(헤더 + '대구광역시' 포함 행)
  iconv -f cp949 -t utf-8 $out.tmp 2>/dev/null | awk 'NR==1 || /대구광역시/' > $out && rm -f $out.tmp
  echo "  kept rows: $(wc -l < $out)"
  python -c "import time; time.sleep(4)"
done; done
echo DONE
