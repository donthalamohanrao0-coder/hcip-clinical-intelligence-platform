#!/bin/bash
cd /home/ubuntu/hcip

echo "=== Health ==="
curl -s http://localhost:8000/health

echo ""
echo "=== Full query test ==="
curl -s -X POST http://localhost:8000/api/v1/query \
  -H "X-API-Key: ${HCIP_API_KEY:?Set HCIP_API_KEY to one of the raw keys in your API_KEYS list}" \
  -H "Content-Type: application/json" \
  -d '{"query":"What is the first-line treatment for type 2 diabetes?","knowledge_base_id":"kb-clinical-2024"}' \
  | python3 -c "
import sys,json
r = json.load(sys.stdin)
print('success:', r['success'])
d = r.get('data',{})
print('response:', d.get('final_response','')[:200])
print('confidence:', d.get('confidence_score'))
print('cache_hit:', d.get('cache_hit'))
print('latency_ms:', round(d.get('total_latency_ms',0),0))
errs = d.get('errors',[])
if errs:
    unique = list(dict.fromkeys(errs))
    print('errors (unique):')
    for e in unique[:5]:
        print(' -', e[:100])
"
