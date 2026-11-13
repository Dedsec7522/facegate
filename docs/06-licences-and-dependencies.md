# Third-party models and dependencies — licence report

All components below permit commercial, self-hosted use. No paid or cloud biometric API is used.

## Pretrained models (vendored in `backend/models/`, loaded locally)

| Model | Purpose | Source | Licence | File | SHA-256 |
|---|---|---|---|---|---|
| YuNet (2023mar) | Face detection + 5 landmarks | OpenCV Zoo `face_detection_yunet` | MIT | `face_detection_yunet_2023mar.onnx` | `8f2383e4…552fa4` |
| face-reidentification-retail-0095 (default) | 256-d face embedding | Intel Open Model Zoo (`models/intel`, FP32 IR) | Apache-2.0 | `face-reidentification-retail-0095.xml` / `.bin` (SHA-384 match the OMZ `model.yml`: `d5adadad…a8ca7a` / `953bb75f…30efda`) | `6cf60c34…80c3` / `21319b95…dd62` |
| SFace (2021dec, fallback) | 128-d face embedding | OpenCV Zoo `face_recognition_sface` | Apache-2.0 | `face_recognition_sface_2021dec.onnx` | `0ba9fbfa…c34e79` |
| MiniFASNet V1SE (scale 4.0) | Passive presentation-attack detection | minivision-ai `Silent-Face-Anti-Spoofing` | Apache-2.0 | `minifasnet_v1se_4.0_80x80.onnx` (exported from `4_0_0_80x80_MiniFASNetV1SE.pth`, SHA-256 `84ee1d37…c5f5990`) | generated |
| MiniFASNet V2 (scale 2.7) | Passive presentation-attack detection | minivision-ai `Silent-Face-Anti-Spoofing` | Apache-2.0 | `minifasnet_v2_2.7_80x80.onnx` (exported from `2.7_80x80_MiniFASNetV2.pth`, SHA-256 `a5eb02e1…99bec0`) | generated |
| anti-spoof-mn3 | Photo / screen replay detection | Intel Open Model Zoo (`models/public/anti-spoof-mn3`, trained on CelebA-Spoof) | MIT | `anti-spoof-mn3.onnx` (SHA-384 matches the OMZ `model.yml`: `6de45349…f92a`) | `c4c99af0…bb3262` |

Notes
- The ONNX export of MiniFASNet uses FaceGate's own network definition (`backend/tools/export_pad_onnx.py`); the vendor's Python module is kept only for reference under `backend/tools/third_party/minifasnet/` with its Apache-2.0 LICENSE.
- The reference repository (`opencv_zoo/models/face_detection_yunet`) contributed **no application code**; only the published MIT detector weights are used, through OpenCV's public `cv2.FaceDetectorYN` API.
- Model training data licences: YuNet and SFace were trained by their authors on WIDER FACE / public face datasets; MiniFASNet on the vendor's proprietary data. FaceGate does not redistribute any dataset.

## Runtime dependencies

| Package | Licence | Package | Licence |
|---|---|---|---|
| FastAPI, Starlette, Uvicorn | MIT / BSD-3 | React, React DOM, React Router | MIT |
| SQLAlchemy, Alembic | MIT | TanStack Query | MIT |
| asyncpg | Apache-2.0 | Motion (`motion`) | MIT |
| pydantic / pydantic-settings | MIT | Recharts | MIT |
| python-jose, cryptography | MIT / Apache-2.0+BSD | Tailwind CSS v4 | MIT |
| argon2-cffi | MIT | lucide-react | ISC |
| pyotp, qrcode | MIT / BSD | zod, react-hook-form | MIT |
| opencv-python(-headless) | Apache-2.0 (OpenCV) | date-fns | MIT |
| onnxruntime | MIT | Inter font (`@fontsource-variable/inter`) | OFL-1.1 |
| openvino | Apache-2.0 | | |
| numpy, pillow | BSD / MIT-CMU | Vite | MIT |
| openpyxl | MIT | PostgreSQL (server) | PostgreSQL Licence |
| httpx, websockets | BSD-3 | Nginx | BSD-2 |

Build-time only (not shipped): PyTorch (BSD-3) for the one-off PAD ONNX export.

Regenerate the full inventory at any time:

```bash
backend/.venv/Scripts/python -m pip install pip-licenses && backend/.venv/Scripts/pip-licenses --format=markdown
cd frontend && npx license-checker --summary
```
