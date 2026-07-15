from inference import InferencePipeline


def my_sink(result, video_frame):
    print(result)  # do something with the predictions of each frame


pipeline = InferencePipeline.init_with_workflow(
    api_key="cn0n30G0fmrKnhZ7ih8q",
    workspace_name="rin-miyazaki",
    workflow_id="goods-and-gap-chinese-vgoods-and-gap-chinese-2-yolo11n-t1-logic",
    video_reference=0,  # Device id (0 for the built-in webcam)
    on_prediction=my_sink,
)
pipeline.start()
pipeline.join()
