# test_load.py 내용을 아래로 교체
import torch
import nemo.collections.asr as nemo_asr

model = nemo_asr.models.ASRModel.from_pretrained("nvidia/parakeet-tdt-0.6b-v3")
model = model.to("cuda" if torch.cuda.is_available() else "cpu")

# ↓ 아까 다운로드됐던 mp3 경로로 수정
TEST_FILE = r"C:\Users\gwakm\Downloads\ICT 2026 MNQ ATH Reversal Again April 23, 2026_audio.mp3"

output = model.transcribe([TEST_FILE], timestamps=True)
result = output[0]

print("\n=== TEXT ===")
print(repr(getattr(result, 'text', 'NONE')))

print("\n=== TIMESTAMP TYPE ===")
ts = getattr(result, 'timestamp', None)
print(type(ts))

print("\n=== TIMESTAMP KEYS ===")
if isinstance(ts, dict):
    print(ts.keys())
    print("segment 수:", len(ts.get('segment', [])))
    print("word 수:", len(ts.get('word', [])))
    print("\n첫 3 segment:")
    for s in ts.get('segment', [])[:3]:
        print(s)
else:
    print(repr(ts))
