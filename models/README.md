# models/

- `best.onnx` — YOLOv8n model trained on VisDrone, used at runtime via
  `onnxruntime`. `pipeline/detect_objects.py` runs it against the raw
  video, frame by frame. Source: https://huggingface.co/mshamrai/yolov8n-visdrone
- `best.pt` — the PyTorch source of the same model (converted to `.onnx`
  with `yolo export`). Not used at runtime and not included in this
  repository; download it from the Hugging Face page above if you need to
  re-export.

Classes: pedestrian, people, bicycle, car, van, truck, tricycle,
awning-tricycle, bus, motor. See the README's "Object detection" section.
