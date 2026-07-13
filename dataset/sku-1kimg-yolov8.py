from roboflow import Roboflow

rf = Roboflow(api_key="")
project = rf.workspace("rin-miyazaki").project("sku-1kimg")
version = project.version(1)
dataset = version.download("yolov8")
