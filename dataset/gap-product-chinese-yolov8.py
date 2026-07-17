from roboflow import Roboflow

api_key = input("Enter your Roboflow API Key: ")
rf = Roboflow(api_key=api_key)
project = rf.workspace("rin-miyazaki").project("gap-product-chinese")
version = project.version(2)
dataset = version.download("yolov8")
