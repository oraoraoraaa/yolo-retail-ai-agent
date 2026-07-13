from roboflow import Roboflow

api_key = input("Enter your Roboflow API Key: ")
rf = Roboflow(api_key=api_key)
project = rf.workspace("rin-miyazaki").project("sku-gap-700img")
version = project.version(1)
dataset = version.download("yolov8")
