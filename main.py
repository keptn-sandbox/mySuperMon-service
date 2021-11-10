import os
import sys
import time
import json
import requests
from flask import Flask, request, Response
from cloudevents.http import from_http, CloudEvent, to_structured
from prometheus_client import Counter, generate_latest, Gauge, Histogram
from keptn import Keptn, start_polling

app = Flask(__name__)
CONTENT_TYPE_LATEST = str('text/plain; version=0.0.4; charset=utf-8')
# Port on which to listen for cloudevents
PORT = os.getenv('RCV_PORT', '8080')
#  Path to which cloudevents are sent
PATH = os.getenv('RCV_PATH', '/')
memory_gauge = Gauge(
    'memory_usage_in_mb',
    'Amount of memory in megabytes currently in use by this container.'
)

@app.route(PATH, methods=["POST"])
def gotevent():
    # create a CloudEvent
    event = from_http(request.headers, request.get_data())
    keptn = Keptn(event)
    keptn.handle_cloud_event()
    return "", 204

#called when deployment triggered and authenticate mysupermon session
def deployment_triggered(keptn: Keptn, shkeptncontext: str, event, data):
    print("Verifying mySuperMon session...")
    Keptn.set_auth(os.environ["MYSUPERMON_USERNAME"], os.environ["MYSUPERMON_PASSWORD"])

# register deployment triggered handler
Keptn.on('deployment.triggered', deployment_triggered)

#metrics endpoint for preometheus target
@app.route('/metrics', methods=['GET'])
def get_run_situation_details():
    headers = {'Authorization': f"Bearer {Keptn.mysupermon_token}",'applicationIdentifier': Keptn.mysupermon_app_identifier,'Content-Type':'application/json'}
    if(Keptn.recording_flag):
        response=requests.get(f"{os.environ['MYSUPERMON_ENDPOINT']}/devaten/data/getRunSituation",headers=headers)
        print(response.json())
        data = json.loads(response.text)
        #get database metrics
        metrics = Keptn.metrics[data["data"]['runSituationResult'][0]["databaseType"]]
        for key in data["data"]['runSituationResult'][0]["data"]:
            if (isinstance(data["data"]['runSituationResult'][0]["data"][key], int)) and (metrics.get(key) is not None):
                metrics[key].observe(data["data"]['runSituationResult'][0]["data"][key])
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)
    else:
        memory_gauge.set(time.time())
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

#Prepare metrics for pushing run situation data
def prepare_metrics():
    f = open('dbconfig/metrics.json',)
    data = json.load(f)
    for dbtype in data:
        Keptn.metrics[dbtype]={}
        for metric in data[dbtype]:
            Keptn.metrics[dbtype][metric["name"]] = Histogram(metric["name"],metric["description"])


def start_recording(keptn: Keptn, shkeptncontext: str, event, data):
    print("------- IN START RECORDING -------")
    details=json.loads(json.dumps(data))
    usecaseIdentifier = f"{details['project']}-{details['service']}-{details['stage']}"
    Keptn.mysupermon_app_identifier = keptn.get_project_resource('mysupermon_app_identifier.txt').decode("utf-8").strip("\n").strip("\t")
    print("mysupermon_app_identifier=", Keptn.mysupermon_app_identifier)
    payload = {'usecaseIdentifier': usecaseIdentifier}
    headers = {'Authorization': f"Bearer {Keptn.mysupermon_token}",
                'applicationIdentifier': Keptn.mysupermon_app_identifier,
                'Content-Type':'application/json'}
    response=requests.get(f"{os.environ['MYSUPERMON_ENDPOINT']}/devaten/data/startRecording",params=payload,headers=headers)
    rs = json.loads(response.text)
    if(rs['responseCode'] == 200):
        keptn.send_task_started_cloudevent(message= f"INFO --> Recording started for usecase => {usecaseIdentifier}", result="pass" , status="succeeded")
        print(f"INFO --> Recording started for usecase => {usecaseIdentifier}")
        #on start recording successful call stop recording
        Keptn.recording_flag = True
        stop_recording(keptn, shkeptncontext, event, data, usecaseIdentifier, headers)
    elif rs['responseCode'] == 400:
        keptn.send_task_started_cloudevent(message="ERROR --> Usecase identifier is null.", result="fail" , status="errored")
        print("ERROR --> Usecase identifier is null.")
    elif rs['responseCode'] == 402:
        keptn.send_task_status_changed_cloudevent(message= "ERROR --> Your mySuperMon package is expired.", result="fail" , status="errored")
        print("ERROR --> Your mySuperMon package is expired.")
    elif rs['responseCode'] == 412:
        keptn.send_task_status_changed_cloudevent(message= "ERROR --> Please activate your mySuperMon subscription key.", result="fail" , status="errored")
        print("ERROR --> Please activate your mySuperMon subscription key.")
    elif rs['responseCode'] == 406:
        keptn.send_task_status_changed_cloudevent(message= "ERROR --> Please fill the details for alert criteria.", result="fail" , status="errored")
        print("ERROR --> Please fill the details for alert criteria.")
    elif rs['responseCode'] == 409:
        keptn.send_task_status_changed_cloudevent(message="ERROR --> Recording already started.", result="fail" , status="errored")
        print("ERROR --> Recording already started.")
    elif rs['responseCode'] == 417:
        keptn.send_task_status_changed_cloudevent(message=f"ERROR --> {rs['errorMessage']}", result="fail" , status="errored")
        print(f"ERROR --> {rs['errorMessage']}")
    elif rs['responseCode'] == 204:
        keptn.send_task_status_changed_cloudevent(message="ERROR --> Error at server side/recording not started due to some error.", result="fail" , status="errored")
        print("ERROR --> Error at server side/recording not started due to some error.")
    elif rs['responseCode'] == 503:
        keptn.send_task_status_changed_cloudevent(message=f"ERROR --> {rs['errorMessage']}", result="fail" , status="errored")
        print(f"ERROR --> {rs['errorMessage']}")
    else:
        keptn.send_task_status_changed_cloudevent(message="ERROR --> There some problem!", result="fail" , status="errored")
        print("ERROR --> There some problem!")


# register start recording handler
Keptn.on('test.triggered', start_recording)

# stop recording 
def stop_recording(keptn: Keptn, shkeptncontext: str, event, data, usecaseIdentifier, headers):
    details=json.loads(json.dumps(data))
    #Listening test finished event for calling stop recording api 
    print("listening for test finished...")
    while True:
        if(Keptn.listen_test_finished(details, shkeptncontext)):
            break
        else:
            time.sleep(10)

    print("------- IN STOP RECORDING -------")
    payload = {'usecaseIdentifier': usecaseIdentifier,'inputSource': 'application'}
    response=requests.get(f"{os.environ['MYSUPERMON_ENDPOINT']}/devaten/data/stopRecording",params=payload,headers=headers)
    print(f"{response.status_code}  -->  {json.loads(response.text)}")
    rs = json.loads(response.text)
    if rs['responseCode'] == 200:
        keptn.send_task_finished_cloudevent(message=f"INFO --> Recording stopped for usecase => {usecaseIdentifier}, Report Link --> {os.environ['MYSUPERMON_ENDPOINT']}/#/report/view/{rs['data'][usecaseIdentifier.upper()][0]['usecaseIdentifier']}/{rs['data'][usecaseIdentifier.upper()][0]['id_num']}", result="pass" , status="succeeded")
        print(f"INFO --> Recording stopped for usecase => {usecaseIdentifier}")
    elif rs['responseCode'] == 406:
        keptn.send_task_status_changed_cloudevent(message="ERROR --> Not authorized to stop recording" , result="fail" , status="errored")
        print("ERROR --> Not authorized to stop recording")
    elif rs['responseCode'] == 304:
        keptn.send_task_status_changed_cloudevent(message="ERROR --> No recording for stop" , result="fail" , status="errored")
        print("ERROR --> No recording for stop")
    elif rs['responseCode'] == 204:
        keptn.send_task_status_changed_cloudevent(message="ERROR --> Error at server side/recording not started due to some error", result="fail" , status="errored")
        print("ERROR --> Error at server side/recording not started due to some error")
    elif rs['responseCode'] == 400:
        keptn.send_task_status_changed_cloudevent(message="ERROR --> Usecase identifier is null", result="fail" , status="errored")
        print("ERROR --> Usecase identifier is null")
    elif rs['responseCode'] == 503:
        keptn.send_task_status_changed_cloudevent(message=f"ERROR --> {rs['errorMessage']}", result="fail" , status="errored")
        print(f"ERROR --> {rs['errorMessage']}")
    elif rs['responseCode'] == 500:
        keptn.send_task_finished_cloudevent(message="ERROR --> No data found data rollbacked successfully." , result="warning" , status="succeeded")
        print("ERROR --> No data found data rollbacked successfully.")
    else:
        keptn.send_task_status_changed_cloudevent(message="ERROR --> There some problem!", result="fail" , status="errored")
        print("ERROR --> There some problem!")
    Keptn.recording_flag = False


if __name__ == "__main__":
    if "KEPTN_API_TOKEN" in os.environ and "KEPTN_ENDPOINT" in os.environ and os.environ["KEPTN_API_TOKEN"] and os.environ["KEPTN_ENDPOINT"] and os.environ["MYSUPERMON_USERNAME"] and os.environ["MYSUPERMON_PASSWORD"] and os.environ['MYSUPERMON_ENDPOINT']:
        print("Found environment variables KEPTN_ENDPOINT and KEPTN_API_TOKEN, polling events from API")
        print("Found enviroment variables MYSUPERMON_USERNAME, MYSUPERMON_PASSWORD, MYSUPERMON_ENDPOINT, Authenticating user ...")
        #Check validity of mysupermon credentials
        Keptn.set_auth(os.environ["MYSUPERMON_USERNAME"], os.environ["MYSUPERMON_PASSWORD"])
        thread = start_polling(os.environ["KEPTN_ENDPOINT"], os.environ["KEPTN_API_TOKEN"])
        #calling prepare_metrics on service start
        prepare_metrics()
        if not thread:
            print("ERROR: Failed to start polling thread, exiting")
            sys.exit(1)

        print("Exit using CTRL-C")
        app.run(host='0.0.0.0', port=PORT)
    else:
        # run flask app with HTTP endpoint
        print("Running on port", PORT, "on path", PATH)
        app.run(host='0.0.0.0', port=PORT)
