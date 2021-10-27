import os
import sys
import time
import json

import requests
from flask import Flask, request
from cloudevents.http import from_http, CloudEvent, to_structured

from keptn import Keptn, start_polling

app = Flask(__name__)

# Port on which to listen for cloudevents
PORT = os.getenv('RCV_PORT', '8080')
#  Path to which cloudevents are sent
PATH = os.getenv('RCV_PATH', '/')
mysupermon_endpoint = os.environ['MYSUPERMON_ENDPOINT']
mysupermon_username = os.environ["MYSUPERMON_USERNAME"]
mysupermon_password = os.environ["MYSUPERMON_PASSWORD"]

@app.route(PATH, methods=["POST"])
def gotevent():
    # create a CloudEvent
    event = from_http(request.headers, request.get_data())

    keptn = Keptn(event)
    keptn.handle_cloud_event()

    return "", 204

def deployment_triggered(keptn: Keptn, shkeptncontext: str, event, data):
    print("Verifying mySuperMon session...")
    Keptn.set_auth(mysupermon_username, mysupermon_password)

Keptn.on('deployment.triggered', deployment_triggered)

def get_run_situation_details(headers):
    response=requests.get(f"{mysupermon_endpoint}/devaten/data/getRunSituation",headers=headers)
    print(response.json())

def start_recording(keptn: Keptn, shkeptncontext: str, event, data):
    print("------- IN START RECORDING -------")
    details=json.loads(json.dumps(data))
    usecaseIdentifier = f"{details['project']}-{details['service']}-{details['stage']}"
    mysupermon_app_identifier = keptn.get_project_resource('mysupermon_app_identifier.txt').decode("utf-8").strip("\n").strip("\t")
    print("mysupermon_app_identifier=", mysupermon_app_identifier)
    payload = {'usecaseIdentifier': usecaseIdentifier}
    headers = {'Authorization': f"Bearer {Keptn.mysupermon_token}",
                'applicationIdentifier': mysupermon_app_identifier,
                'Content-Type':'application/json'}
    response=requests.get(f"{mysupermon_endpoint}/devaten/data/startRecording",params=payload,headers=headers)
    print(f"{response.status_code}  -->  {json.loads(response.text)}")
    rs = json.loads(response.text)
    if(rs['responseCode'] == 200):
        keptn.send_task_started_cloudevent(message= f"INFO --> Recording started for usecase => {usecaseIdentifier}", result="pass" , status="succeeded")
        print(f"INFO --> Recording started for usecase => {usecaseIdentifier}")
        #on start recording successful call stop recording
        stop_recording(keptn, shkeptncontext, event, data, mysupermon_app_identifier)
    elif rs['responseCode'] == 400:
        keptn.send_task_started_cloudevent(message="ERROR --> Usecase identifier is null.", result="fail" , status="errored")
        print("ERROR --> Usecase identifier is null.")
    elif rs['responseCode'] == 402:
        keptn.send_task_started_cloudevent(message= "ERROR --> Your mySuperMon package is expired.", result="fail" , status="errored")
        print("ERROR --> Your mySuperMon package is expired.")
    elif rs['responseCode'] == 412:
        keptn.send_task_started_cloudevent(message= "ERROR --> Please activate your mySuperMon subscription key.", result="fail" , status="errored")
        print("ERROR --> Please activate your mySuperMon subscription key.")
    elif rs['responseCode'] == 406:
        keptn.send_task_started_cloudevent(message= "ERROR --> Please fill the details for alert criteria.", result="fail" , status="errored")
        print("ERROR --> Please fill the details for alert criteria.")
    elif rs['responseCode'] == 409:
        keptn.send_task_started_cloudevent(message="ERROR --> Recording already started.", result="fail" , status="errored")
        print("ERROR --> Recording already started.")
    elif rs['responseCode'] == 417:
        keptn.send_task_started_cloudevent(message=f"ERROR --> {rs['errorMessage']}", result="fail" , status="errored")
        print(f"ERROR --> {rs['errorMessage']}")
    elif rs['responseCode'] == 204:
        keptn.send_task_started_cloudevent(message="ERROR --> Error at server side/recording not started due to some error.", result="fail" , status="errored")
        print("ERROR --> Error at server side/recording not started due to some error.")
    elif rs['responseCode'] == 503:
        keptn.send_task_started_cloudevent(message=f"ERROR --> {rs['errorMessage']}", result="fail" , status="errored")
        print(f"ERROR --> {rs['errorMessage']}")
    else:
        keptn.send_task_started_cloudevent(message="ERROR --> There some problem!", result="fail" , status="errored")
        print("ERROR --> There some problem!")


# register start recording handler
Keptn.on('test.triggered', start_recording)

def stop_recording(keptn: Keptn, shkeptncontext: str, event, data, mysupermon_app_identifier):
    details=json.loads(json.dumps(data))
    headers = {'Authorization': f"Bearer {Keptn.mysupermon_token}",
               'applicationIdentifier': mysupermon_app_identifier,
               'Content-Type':'application/json'}
    print("listening for test finished...")
    while True:
        if(Keptn.listen_test_finished(details, shkeptncontext)):
            break
        else:
            get_run_situation_details(headers)
            time.sleep(10)
    
    print("------- IN STOP RECORDING -------")
    usecaseIdentifier = f"{details['project']}-{details['service']}-{details['stage']}"
    print("mysupermon_app_identifier=", mysupermon_app_identifier)
    payload = {'usecaseIdentifier': usecaseIdentifier,'inputSource': 'application'}
    response=requests.get(f"{mysupermon_endpoint}/devaten/data/stopRecording",params=payload,headers=headers)
    print(f"{response.status_code}  -->  {json.loads(response.text)}")
    rs = json.loads(response.text)
    if rs['responseCode'] == 200:
        keptn.send_task_finished_cloudevent(message=f"INFO --> Recording stopped for usecase => {usecaseIdentifier}, Report Link --> {mysupermon_endpoint}/#/report/view/{rs['data'][usecaseIdentifier.upper()][0]['usecaseIdentifier']}/{rs['data'][usecaseIdentifier.upper()][0]['id_num']}", result="pass" , status="succeeded")
        print(f"INFO --> Recording stopped for usecase => {usecaseIdentifier}")
    elif rs['responseCode'] == 406:
        keptn.send_task_finished_cloudevent(message="ERROR --> Not authorized to stop recording" , result="fail" , status="errored")
        print("ERROR --> Not authorized to stop recording")
    elif rs['responseCode'] == 304:
        keptn.send_task_finished_cloudevent(message="ERROR --> No recording for stop" , result="fail" , status="errored")
        print("ERROR --> No recording for stop")
    elif rs['responseCode'] == 204:
        keptn.send_task_finished_cloudevent(message="ERROR --> Error at server side/recording not started due to some error", result="fail" , status="errored")
        print("ERROR --> Error at server side/recording not started due to some error")
    elif rs['responseCode'] == 400:
        keptn.send_task_finished_cloudevent(message="ERROR --> Usecase identifier is null", result="fail" , status="errored")
        print("ERROR --> Usecase identifier is null")
    elif rs['responseCode'] == 503:
        keptn.send_task_finished_cloudevent(message=f"ERROR --> {rs['errorMessage']}", result="fail" , status="errored")
        print(f"ERROR --> {rs['errorMessage']}")
    elif rs['responseCode'] == 500:
        keptn.send_task_finished_cloudevent(message="ERROR --> No data found data rollbacked successfully." , result="warning" , status="succeeded")
        print("ERROR --> No data found data rollbacked successfully.")
    else:
        keptn.send_task_finished_cloudevent(message="ERROR --> There some problem!", result="fail" , status="errored")
        print("ERROR --> There some problem!")



if __name__ == "__main__":
    if "KEPTN_API_TOKEN" in os.environ and "KEPTN_ENDPOINT" in os.environ and os.environ["KEPTN_API_TOKEN"] and os.environ["KEPTN_ENDPOINT"] and mysupermon_username and mysupermon_password and mysupermon_endpoint:
        print("Found environment variables KEPTN_ENDPOINT and KEPTN_API_TOKEN, polling events from API")
        print("Found enviroment variables MYSUPERMON_USERNAME, MYSUPERMON_PASSWORD, MYSUPERMON_ENDPOINT, Authenticating user ...")
        Keptn.set_auth(mysupermon_username, mysupermon_password)
        thread = start_polling(os.environ["KEPTN_ENDPOINT"], os.environ["KEPTN_API_TOKEN"])

        if not thread:
            print("ERROR: Failed to start polling thread, exiting")
            sys.exit(1)

        print("Exit using CTRL-C")

        # wait til exit (e.g., using CTRL C)
        while True:
            try:
                time.sleep(0.5)
            except KeyboardInterrupt:
                print("Exiting...")
                sys.exit(0)

    else:
        # run flask app with HTTP endpoint
        print("Running on port", PORT, "on path", PATH)
        app.run(host='0.0.0.0', port=PORT)
