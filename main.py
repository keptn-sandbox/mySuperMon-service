Skip to content
Search or jump to…
Pull requests
Issues
Marketplace
Explore
 
@MikkoLarke 
keptn-sandbox
/
mySuperMon-service
Public
Code
Issues
Pull requests
1
Actions
Projects
Wiki
Security
Insights
Settings
mySuperMon-service/main.py /
@nic07patil
nic07patil Implementation done for stop recording metrics and deftect resolved.
Latest commit 5c7a6ba on Nov 17, 2021
 History
 1 contributor
 216 lines (195 sloc)  12.4 KB
   
import os
import sys
import time
import json
import requests
from flask import Flask, request, Response
from cloudevents.http import from_http, CloudEvent, to_structured
from prometheus_client import generate_latest, Gauge, Histogram
from keptn import Keptn, start_polling
from tabulate import tabulate

app = Flask(__name__)
CONTENT_TYPE_LATEST = str('text/plain; version=0.0.4; charset=utf-8')
# Port on which to listen for cloudevents
PORT = os.getenv('RCV_PORT', '8080')
#  Path to which cloudevents are sent
PATH = os.getenv('RCV_PATH', '/')
MYSUPERMON_START_RECORDING = "/devaten/data/startRecording"
MYSUPERMON_STOP_RECORDING = "/devaten/data/stopRecording"
MYSUPERMON_RUN_SITUATION = "/devaten/data/getRunSituation"
MYSUPERMON_GET_ALERT_CONFIG = "/devaten/data/getAlertConfigInfoByApplicationIdentifier"
memory_gauge = Gauge('sample','sample')

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
    #If recording started push run situation metrics
    if(Keptn.recording_flag):
        response=requests.get(f"{os.environ['MYSUPERMON_ENDPOINT']}{MYSUPERMON_RUN_SITUATION}",headers=headers)
        #print(response.json())
        data = json.loads(response.text)
        #get database metrics
        Keptn.dbtype = data["data"]['runSituationResult'][0]["databaseType"]
        metrics = Keptn.run_metrics[Keptn.dbtype]
        for key in data["data"]['runSituationResult'][0]["data"]:
            if (isinstance(data["data"]['runSituationResult'][0]["data"][key], int)) and (metrics.get(key) is not None):
                metrics[key].labels(data["data"]["usecaseIdentifier"]).observe(data["data"]['runSituationResult'][0]["data"][key])
    #If recording stopped push stop recording metrics
    elif bool(Keptn.stop_payload):
        stop_metrics = Keptn.stop_metrics[Keptn.dbtype]
        for column in Keptn.stop_payload:
            stop_metrics[column["columnName"]].labels(Keptn.stop_metrics["usecaseId"]).observe(column["newValue"])
        Keptn.stop_payload.clear()
    #if there is no recording started or stopped push sample data
    else:
        memory_gauge.set(time.time())
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


#Prepare metrics for pushing run situation data
def prepare_metrics():
    f = open('dbconfig/metrics.json',)
    data = json.load(f)
    for dbtype in data:
        Keptn.run_metrics[dbtype]={}
        for metric in data[dbtype]:
            Keptn.run_metrics[dbtype][metric["name"]] = Histogram(metric["name"],metric["description"],["usecaseIdentifier"])
    

def prepare_stop_recording_metrics(headers, usecaseIdentifier):
    Keptn.stop_metrics["usecaseId"] = usecaseIdentifier
    #Get alert config details by application identifier
    response = requests.get(f"{os.environ['MYSUPERMON_ENDPOINT']}{MYSUPERMON_GET_ALERT_CONFIG}", headers=headers)
    rs = json.loads(response.text)
    #Check if dbtype key not present and initialize dict using dbtype 
    if Keptn.dbtype not in Keptn.stop_metrics:
        Keptn.stop_metrics[Keptn.dbtype] = {}
    #Compare len of response data and Keptn.stop_metrics to reinitialization of metrics
    if len(Keptn.stop_metrics[Keptn.dbtype])!=len(rs['data']):
        for column in rs['data']:
            if column['columnName'] not in Keptn.stop_metrics[Keptn.dbtype]:
                Keptn.stop_metrics[Keptn.dbtype][column['columnName']] = Histogram(column["columnName"],"New value",["usecaseIdentifier"])
    

def start_recording(keptn: Keptn, shkeptncontext: str, event, data):
    print("------- IN START RECORDING -------")
    details=json.loads(json.dumps(data))
    usecaseIdentifier = f"{details['project']}-{details['service']}-{details['stage']}".upper()
    Keptn.mysupermon_app_identifier = keptn.get_project_resource('mysupermon_app_identifier.txt').decode("utf-8").strip("\n").strip("\t")
    print("mysupermon_app_identifier=", Keptn.mysupermon_app_identifier)
    payload = {'usecaseIdentifier': usecaseIdentifier}
    headers = {'Authorization': f"Bearer {Keptn.mysupermon_token}",
                'applicationIdentifier': Keptn.mysupermon_app_identifier,
                'Content-Type':'application/json'}
    response=requests.get(f"{os.environ['MYSUPERMON_ENDPOINT']}{MYSUPERMON_START_RECORDING}",params=payload,headers=headers)
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
            time.sleep(5)

    print("------- IN STOP RECORDING -------")
    #calling prepare_stop_recording_metrics method for creating alert config metrics dict object 
    prepare_stop_recording_metrics(headers, usecaseIdentifier)
    payload = {'usecaseIdentifier': usecaseIdentifier,'inputSource': 'application'}
    response=requests.get(f"{os.environ['MYSUPERMON_ENDPOINT']}{MYSUPERMON_STOP_RECORDING}",params=payload,headers=headers)
    #print(f"{response.status_code}  -->  {json.loads(response.text)}")
    rs = json.loads(response.text)
    if rs['responseCode'] == 200:
        #create a message string with stop recording payload details.
        tabledata = []
        for obj in rs['data'][usecaseIdentifier][0]['valueObjectList']:
            tabledata.append([obj["columnName"],obj["oldValue"],obj["newValue"],obj["comparedNumber"]])
        pr = tabulate(tabledata,headers=["Column Name","Old Value","New Value", "Result"])
        #Add stop payload data for pushing metrics to prometheus
        Keptn.stop_payload = rs['data'][usecaseIdentifier][0]['valueObjectList']
        keptn.send_task_finished_cloudevent(message=f"INFO --> Recording stopped. \nReport Link : {os.environ['MYSUPERMON_ENDPOINT']}/#/report/view/{rs['data'][usecaseIdentifier][0]['usecaseIdentifier']}/{rs['data'][usecaseIdentifier][0]['id_num']} \nUsecase : {rs['data'][usecaseIdentifier][0]['usecaseIdentifier']}            {rs['data'][usecaseIdentifier][0]['result']}({rs['data'][usecaseIdentifier][0]['resultInPercentage']}%)\nStart Timestamp : {rs['data'][usecaseIdentifier][0]['starttimestamp']} \n\n{pr}", result="pass" , status="succeeded")
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
    if os.environ["MYSUPERMON_USERNAME"] and os.environ["MYSUPERMON_PASSWORD"] and os.environ['MYSUPERMON_ENDPOINT']:
        print("Found enviroment variables MYSUPERMON_USERNAME, MYSUPERMON_PASSWORD, MYSUPERMON_ENDPOINT, \nAuthenticating user ...")
        Keptn.set_auth(os.environ["MYSUPERMON_USERNAME"], os.environ["MYSUPERMON_PASSWORD"])
        #calling prepare_metrics on service start
        prepare_metrics()

    if "KEPTN_API_TOKEN" in os.environ and "KEPTN_ENDPOINT" in os.environ and os.environ["KEPTN_API_TOKEN"] and os.environ["KEPTN_ENDPOINT"]:
        print("Found environment variables KEPTN_ENDPOINT and KEPTN_API_TOKEN, polling events from API")
        thread = start_polling(os.environ["KEPTN_ENDPOINT"], os.environ["KEPTN_API_TOKEN"])
        if not thread:
            print("ERROR: Failed to start polling thread, exiting")
            sys.exit(1)

        print("Exit using CTRL-C")
        # For using prometheus in DEV enviroment
        app.run(host='0.0.0.0', port=PORT)
    else:
        # run flask app with HTTP endpoint
        print("Running on port", PORT, "on path", PATH)
        app.run(host='0.0.0.0', port=PORT)
