"""Minimal pipe decoder diagnostic — tests file, pipe+close, and pipe+persistent."""
import subprocess, sys, os, time, threading

sys.path.insert(0, "backend")
from cv_engine.services.dvrip_client import DVRIPClient
from cv_engine.services.dvrip_frames import TYPE_I_FRAME

def read_all(pipe, timeout=5):
    """Read from a pipe with timeout using a thread."""
    result = [b""]
    def _read():
        try:
            result[0] = pipe.read(1048576)
        except:
            pass
    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout)
    return result[0]

def read_stderr(proc, timeout=3):
    """Read stderr with timeout."""
    result = [b""]
    def _read():
        try:
            result[0] = proc.stderr.read(65536)
        except:
            pass
    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout)
    return result[0]

# Get I-frame
client = DVRIPClient("192.168.1.35", 34567, "uxdp", "cw8adc")
client.connect(channel=0)
print("Connected, waiting for I-frame...")
iframe = None
for ptype, payload, meta in client.iter_packets():
    if ptype == TYPE_I_FRAME:
        iframe = payload
        print(f"Got I-frame: {len(payload)} bytes")
        break
client.close()
if not iframe:
    print("No I-frame"); sys.exit(1)

# TEST 1: File-based (known working)
print("\n=== TEST 1: File-based ===")
with open("_t.h265", "wb") as f: f.write(iframe)
r = subprocess.run(
    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "hevc", "-i", "_t.h265",
     "-frames:v", "1", "-f", "mjpeg", "-q:v", "3", "-y", "_t1.jpg"],
    capture_output=True, timeout=10
)
if os.path.exists("_t1.jpg") and os.path.getsize("_t1.jpg") > 100:
    print(f"OK: {os.path.getsize('_t1.jpg')} bytes")
else:
    print(f"FAIL: rc={r.returncode} stderr={r.stderr[:200]}")
os.unlink("_t.h265")

# TEST 2: Pipe — write all then close stdin (simulates sp.run behavior)
print("\n=== TEST 2: Pipe + close stdin (EOF) ===")
r2 = subprocess.run(
    ["ffmpeg", "-hide_banner", "-loglevel", "error",
     "-f", "hevc", "-i", "pipe:0",
     "-frames:v", "1", "-f", "mjpeg", "-q:v", "3", "-y", "_t2.jpg"],
    input=iframe, capture_output=True, timeout=10
)
if os.path.exists("_t2.jpg") and os.path.getsize("_t2.jpg") > 100:
    print(f"OK: {os.path.getsize('_t2.jpg')} bytes")
else:
    print(f"FAIL: rc={r2.returncode} stderr={r2.stderr[:200]}")

# TEST 3: Pipe — write + trailing start code, NO close, read with timeout
print("\n=== TEST 3: Pipe + trailing start code (persistent) ===")
NAL_TERM = b"\x00\x00\x00\x01"
proc = subprocess.Popen(
    ["ffmpeg", "-hide_banner", "-loglevel", "error",
     "-fflags", "nobuffer", "-probesize", "32768", "-analyzeduration", "0",
     "-f", "hevc", "-i", "pipe:0",
     "-flags", "low_delay",
     "-f", "mjpeg", "-q:v", "3", "pipe:1"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    bufsize=0,
)
proc.stdin.write(iframe + NAL_TERM)
proc.stdin.flush()

jpeg_out = read_all(proc.stdout, timeout=5)
err3 = read_stderr(proc, timeout=1)
proc.kill()

soi = jpeg_out.find(b"\xff\xd8")
eoi = jpeg_out.find(b"\xff\xd9")
if soi >= 0 and eoi >= 0:
    with open("_t3.jpg", "wb") as f: f.write(jpeg_out[soi:eoi+2])
    print(f"OK: {eoi+2-soi} bytes")
else:
    print(f"FAIL: got {len(jpeg_out)} bytes, no JPEG markers (SOI={soi} EOI={eoi})")
    if err3: print(f"  stderr: {err3.decode(errors='replace')[:300]}")

# TEST 4: Pipe — write + close stdin, read stdout
print("\n=== TEST 4: Pipe + close stdin, read stdout ===")
proc4 = subprocess.Popen(
    ["ffmpeg", "-hide_banner", "-loglevel", "error",
     "-f", "hevc", "-i", "pipe:0",
     "-frames:v", "1", "-f", "mjpeg", "-q:v", "3", "pipe:1"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    bufsize=0,
)
proc4.stdin.write(iframe)
proc4.stdin.close()

jpeg_out4 = read_all(proc4.stdout, timeout=5)
err4 = read_stderr(proc4, timeout=1)
proc4.kill()

soi4 = jpeg_out4.find(b"\xff\xd8")
eoi4 = jpeg_out4.find(b"\xff\xd9")
if soi4 >= 0 and eoi4 >= 0:
    with open("_t4.jpg", "wb") as f: f.write(jpeg_out4[soi4:eoi4+2])
    print(f"OK: {eoi4+2-soi4} bytes")
else:
    print(f"FAIL: got {len(jpeg_out4)} bytes, no JPEG markers (SOI={soi4} EOI={eoi4})")
    if err4: print(f"  stderr: {err4.decode(errors='replace')[:300]}")

# TEST 5: Multiple I-frames through persistent pipe (the actual use case)
print("\n=== TEST 5: Persistent pipe, 5 I-frames ===")
proc5 = subprocess.Popen(
    ["ffmpeg", "-hide_banner", "-loglevel", "error",
     "-fflags", "nobuffer", "-probesize", "32768", "-analyzeduration", "0",
     "-f", "hevc", "-i", "pipe:0",
     "-flags", "low_delay",
     "-f", "mjpeg", "-q:v", "3", "pipe:1"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    bufsize=0,
)

# Get 5 I-frames
client2 = DVRIPClient("192.168.1.35", 34567, "uxdp", "cw8adc")
client2.connect(channel=0)
frames = []
for ptype, payload, meta in client2.iter_packets():
    if ptype == TYPE_I_FRAME:
        frames.append(payload)
        print(f"  Got I-frame #{len(frames)}: {len(payload)} bytes")
        if len(frames) >= 5:
            break
client2.close()

frame_count = 0
for i, f in enumerate(frames):
    print(f"  Writing I-frame #{i+1}...")
    try:
        proc5.stdin.write(f + NAL_TERM)
        proc5.stdin.flush()
    except:
        print(f"  stdin write failed"); break
    
    out = read_all(proc5.stdout, timeout=3)
    soi5 = out.find(b"\xff\xd8")
    eoi5 = out.find(b"\xff\xd9")
    if soi5 >= 0 and eoi5 >= 0:
        frame_count += 1
        print(f"  -> JPEG #{frame_count}: {eoi5+2-soi5} bytes")
    else:
        print(f"  -> No JPEG ({len(out)} bytes)")

err5 = read_stderr(proc5, timeout=1)
proc5.kill()
print(f"  Result: {frame_count}/{len(frames)} frames decoded")
if err5: print(f"  stderr: {err5.decode(errors='replace')[:300]}")

# Cleanup
for f in ["_t1.jpg", "_t2.jpg", "_t3.jpg", "_t4.jpg"]:
    try: os.unlink(f)
    except: pass
