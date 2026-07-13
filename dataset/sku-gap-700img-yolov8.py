from roboflow import Roboflow

rf = Roboflow(api_key="")
project = rf.workspace("rin-miyazaki").project("sku-gap-700img")
version = project.version(1)
dataset = version.download("yolov8")
