# spec018 Mini Takeout Archive Fixture

Synthetic Google Takeout archive for spec 018 TDD tests.

## Contents

- `YouTube and YouTube Music/videos/`: 3 synthetic mp4 files (5s each, 16kHz AAC audio, 128x128 H.264 video)
- `YouTube and YouTube Music/history/watch-history.json`: 3 video entries + 2 metadata-only entries

## Files

| File | Duration | Size |
|------|----------|------|
| 간호학개론 1주차.mp4 | 5s | ~28K |
| 성인간호학 2주차.mp4 | 5s | ~28K |
| 기초해부학 3주차.mp4 | 5s | ~28K |

Total: ~84K

## Generation

Generated with ffmpeg using synthetic sine tone (440Hz) + black video frame:

```sh
ffmpeg -f lavfi -i "sine=frequency=440:duration=5" -f lavfi -i "color=c=black:size=128x128:duration=5:rate=25" \
  -c:a aac -b:a 32k -c:v libx264 -pix_fmt yuv420p -t 5 "${title}.mp4"
```

## Notes

- Files are small enough for CI (total < 100K). No Git LFS needed.
- watch-history.json contains 3 mp4-mapped entries + 2 metadata-only entries (삭제/비공개 videos).
- Not derived from real lecture content; safe to commit.
