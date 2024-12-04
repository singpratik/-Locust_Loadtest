import os
import random
import time
import logging
import csv
import requests
import urllib3
from locust import HttpUser, task, between
import json

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Improved user credentials loading function
def load_user_credentials(file_path):
    credentials = []
    try:
        with open(file_path, mode='r') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if "Email" in row and "Password" in row:
                    credentials.append({"email": row["Email"], "password": row["Password"]})
                else:
                    logger.warning(f"Skipping row due to missing Email or Password: {row}")
    except FileNotFoundError:
        logger.error(f"Credentials file not found: {file_path}")
    except Exception as e:
        logger.error(f"Error reading CSV file: {str(e)}")
    
    if not credentials:
        logger.error("No valid user credentials found. Please check your CSV file.")
    
    return credentials

# Dynamically get the path to the user credentials CSV
def get_credentials_path():
    # Try multiple potential paths
    potential_paths = [
        '/Users/pratiksingh/Desktop/No-code-automation-demo-main/TopcoderAutomationDemo/LoadTest/user_cred.csv',
        os.path.join(os.path.dirname(__file__), 'user_cred.csv'),
        'user_cred.csv'
    ]
    
    for path in potential_paths:
        if os.path.exists(path):
            return path
    
    raise FileNotFoundError("Could not find user_cred.csv file")

# Load user credentials
try:
    USER_CREDENTIALS = load_user_credentials(get_credentials_path())
except FileNotFoundError as e:
    logger.error(str(e))
    USER_CREDENTIALS = []

class InterviewUser(HttpUser):
    wait_time = between(2, 10)
    host = "https://api-uat-us-candidate.vmock.dev"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_uid = None
        self.access_token = None
        self.current_interview_id = None
        
        # Ensures we always have a valid set of credentials
        if not USER_CREDENTIALS:
            raise ValueError("No user credentials available for load testing")

    def on_start(self):
        """Initialize the user session with robust login handling"""
        max_login_attempts = 100
        for attempt in range(max_login_attempts):
            try:
                # Ensure we have credentials even with many concurrent users
                self.user_credentials = random.choice(USER_CREDENTIALS)
                
                if self.login():
                    break
                
                logger.warning(f"Login attempt {attempt + 1} failed. Retrying...")
                time.sleep(2)
            except Exception as e:
                logger.error(f"Login error on attempt {attempt + 1}: {str(e)}")
        else:
            logger.error("Failed to login after multiple attempts. Skipping this user.")
            self.environment.runner.quit()
    

    def log_response_data(self, request_name, response_data):
        """
        Log response data for monitoring and debugging purposes
        
        Args:
            request_name (str): Name/identifier for the request
            response_data (dict): Response data to log
        """
        self.environment.events.request.fire(
            request_type="GET",
            name=request_name,
            response_time=int(time.time() * 1000),
            response_length=len(json.dumps(response_data)),
            response=response_data,
            context={},
            exception=None,
        )            

    @task(1)
    def execute_interview_flow(self):
        """Execute the complete interview flow"""
        if not self.access_token:
            logger.error("Not logged in")
            return

        if not self.create_elevator_pitch():
            logger.error("Failed to create elevator pitch")
            return

        time.sleep(2)

        if not self.start_calibration():
            logger.error("Failed to start calibration")
            return

        time.sleep(2)

        if not self.start_interview():
            logger.error("Failed to start interview")
            return
        time.sleep(2)

        if not self.end_interview():
            logger.error("Failed to end interview")
            return

        # Call the status check after ending the interview
        if not self.duration_clip():
           logger.error("Failed to check duration clip status")
        
        # Call the status check after ending the interview
        if not self.check_elevator_pitch_status():
           logger.error("Failed to check elevator pitch status")
       
        
#Hit_Login
    def login(self):
        """Perform login and return True if successful"""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "LocustTest/1.0"  # Custom User-Agent (change as needed)
        }
        payload = {
            "email": self.user_credentials["email"],
            "password": self.user_credentials["password"],
            "provider": "email"
        }
        logger.info(f"Attempting to login with email: {self.user_credentials['email']} and password: {self.user_credentials['password']}")

        with self.client.post(
            "/dashboard-api-accounts/api/v1/login/common",
            json=payload,
            headers=headers,
            catch_response=True,
            name="/login"
        ) as response:
             response_data = response.json()
        logger.info(f"Login response: {response_data}")  # Log the entire response data for debugging
        
        if response.status_code == 200:
            self.access_token = response_data.get('access_token')
            if self.access_token:
                logger.info(f"Access token successfully retrieved for user: {self.user_credentials['email']}")
                logger.debug(f"Access Token: {self.access_token}")  # Log the access token for verification
                logger.info(f"Login successful for user: {self.user_credentials['email']}")
                return True
            else:
                logger.error("Access token not found in the response")
        else:
            logger.error(f"Login failed for user: {self.user_credentials['email']} with status {response.status_code}")

        return False
    
#Hit_create_ep        
        
    def create_elevator_pitch(self):
        """Create elevator pitch and return True if successful"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }
        payload = {
            "question_id": 1,
            "language": "en"
        }
        logger.info(f"Creating elevator pitch with payload: {payload}")

        with self.client.post(
            "/interviews-api/v1/elevator-pitch/create",
            json=payload,
            headers=headers,
            catch_response=True,
            name="/elevator-pitch/create"
        ) as response:
            if response.status_code in [200, 201]:
                response_data = response.json()
                logger.info(f"Response data: {response_data}")  # Log the entire response data
                self.current_interview_id = response_data.get('interview_id')
                
                # Extract UID from question_data
                print(response_data)
                question_data = response_data.get('question_data', {})
                
                self.current_uid = next(iter(question_data))
                print("hurray", self.current_uid)

                
                logger.info(f"Elevator pitch created - Interview ID: {self.current_interview_id}, UID: {self.current_uid}")
                return True
            else:
                logger.error(f"Failed to create elevator pitch: {response.status_code}, Response: {response.text}")
                return False
            
#Hit_start_calibration            

    def start_calibration(self):
        """Start the calibration"""
        if not self.access_token or not self.current_interview_id:
            logger.error("Missing access token or interview ID")
            return False

        headers = {"Authorization": f"Bearer {self.access_token}"}
        calibration_payload = {
            "clip_id": 10000,
            "interview_id": self.current_interview_id,
            "uid": self.current_uid  # Use current_uid here
        }
        print("calibration_payload", calibration_payload)
        video_file_path = "/Users/pratiksingh/Desktop/No-code-automation-demo-main/TopcoderAutomationDemo/LoadTest/calibration_324456_40000.mkv"
        
        if not os.path.exists(video_file_path):
            logger.error(f"Calibration video file does not exist at {video_file_path}")
            return False

        with open(video_file_path, "rb") as video_file:
            files = {"clip": (os.path.basename(video_file_path), video_file, "video/x-matroska")}
            
            with self.client.post(
                "/interviews-api/v1/interview/calibration",
                data=calibration_payload,
                files=files,
                headers=headers,
                catch_response=True,
                name="/interview/calibration"
            ) as response:
                if response.ok:
                    response_data = response.json()
                    if 'uid' in response_data:
                        self.current_uid = response_data['uid']
                        logger.info(f"Updated UID from calibration response: {self.current_uid}")
                    logger.info(f"Calibration started successfully with interview_id: {self.current_interview_id}")
                    return True
                logger.error(f"Failed to start calibration: {response.status_code}")
                return False

#Hit_start_interview            

    def start_interview(self):
        """Start the interview and upload video and audio clips."""
        if not self.access_token or not self.current_interview_id:
            logger.error("Missing access token or interview ID")
            return False

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "clip_id": 10000,
            "interview_id": self.current_interview_id,
            "tentative_duration": 420,
            "uid": self.current_uid  # Use current_uid here
        }

        try:
            with self.client.post(
                "/interviews-api/v1/interview/start",
                json=payload,
                headers=headers,
                catch_response=True,
                name="/interview/start"
            ) as response:
                if response.status_code != 200:
                    logger.error(f"Failed to start interview: {response.status_code} - {response.text}")
                    return False

                response_data = response.json()
                if 'uid' in response_data:
                    self.current_uid = response_data['uid']
                
                upload_urls = response_data.get('upload_urls', {})
                video_urls = upload_urls.get('video_urls', [])
                audio_urls = upload_urls.get('audio_chunks_urls', [])

                video_directory = "/Users/pratiksingh/Desktop/No-code-automation-demo-main/TopcoderAutomationDemo/LoadTest/clips"
                audio_directory = "/Users/pratiksingh/Desktop/No-code-automation-demo-main/TopcoderAutomationDemo/LoadTest/clips"

                video_files = self.get_local_files(video_directory, ['.mkv', '.mp4'])
                audio_files = self.get_local_files(audio_directory, ['.wav', '.mp3'])

                # Get count of video files
                self.video_count = len(video_files)
                logger.info(f"Number of video files found: {self.video_count}")

                # Upload and process audio files
                for i, audio_url in enumerate(audio_urls):
                    if i >= len(audio_files):
                        break

                    is_last = False

                    if(i == len(audio_files) - 1):
                       is_last = True
                    if self.upload_audio_clip(audio_files[i], audio_url):
                        if not self.process_audio_clip(i, is_last):
                            logger.error(f"Failed to process audio clip {i}")
                    else:
                        logger.error(f"Failed to upload audio {audio_files[i]}")

                for j, video_url in enumerate(video_urls):
                    if j >= len(video_files):
                        break
                    
                    if self.upload_video_clip(video_files[j], video_url):
                        if not self.process_video_clip(j):
                            logger.error(f"Failed to process video clip {j}")
                    else:
                        logger.error(f"Failed to upload video {video_files[j]}")

                return True

        except Exception as e:
            logger.error(f"Exception in start_interview: {str(e)}")
            return False

#get_local_files        

    def get_local_files(self, directory, extensions):
        """Retrieve a list of files from a directory with specified extensions."""
        files = []
        try:
            if os.path.isdir(directory):
                for file in os.listdir(directory):
                    if any(file.endswith(ext) for ext in extensions):
                        files.append(os.path.join(directory, file))
                logger.info(f"Found files in {directory}: {files}")
            else:
                logger.error(f"{directory} is not a valid directory.")
        except Exception as e:
            logger.error(f"Error accessing directory {directory}: {str(e)}")
        return files
    
#Hit_upload_video_clip   

    def upload_video_clip(self, file_path, upload_url):
        """Upload video clip to the specified URL"""
        if not os.path.exists(file_path):
            logger.error(f"Video file not found: {file_path}")
            return False
        
        try:
            with open(file_path, 'rb') as video_file:
                response = requests.put(
                    upload_url,
                    data=video_file,
                    headers={"Content-Type": "video/x-matroska"},
                    timeout=60
                )
                if response.status_code in [200, 204]:
                    logger.info(f"Video uploaded successfully: {file_path}")
                    return True
                logger.error(f"Failed to upload video: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Error uploading video: {str(e)}")
            return False

#Hit_upload_audio_clip       

    def upload_audio_clip(self, file_path, upload_url):
        """Upload audio clip to S3 using presigned URL"""
        if not os.path.exists(file_path):
            logger.error(f"Audio file not found: {file_path}")
            return False

        try:
            http = urllib3.PoolManager()
            
            with open(file_path, 'rb') as audio_file:
                response = http.request(
                    'PUT',
                    upload_url,
                    body=audio_file.read(),
                    timeout=urllib3.Timeout(connect=5, read=60),
                    retries=False
                )
            
            if response.status in [200, 204]:
                logger.info(f"Successfully uploaded {file_path}")
                return True
            else:
                logger.error(f"Upload failed. Status: {response.status}")
                return False

        except Exception as e:
            logger.error(f"Error during audio upload: {str(e)}")
            return False
        
#Hit_process_audio_clip        

    def process_audio_clip(self, clip_id, is_last = False):
        """Process uploaded audio clip"""
        if not self.access_token or not self.current_interview_id:
            logger.error("Missing access token or interview ID")
            return False

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

        payload = {
            "interview_id": self.current_interview_id,
            "clip_id": clip_id,
            "uid": self.current_uid,  # Use current_uid here
            "is_last": is_last
        }

        with self.client.post(
            "/interviews-api/v1/interview/process/audio-clip",
            json=payload,
            headers=headers,
            catch_response=True,
            name="/interview/process/audio-clip"
        ) as response:
            if response.status_code == 200:
                response_data = response.json()
                logger.info(f"audio clip response_data {response_data}")
                if 'uid' in response_data:
                    self.current_uid = response_data['uid']
                logger.info(f"Successfully processed audio clip {clip_id}")
                return True
            logger.error(f"Failed to process audio clip {clip_id}: {response.status_code}")
            return False
        
#Hit_process_video_clip 
     
    def process_video_clip(self, clip_id):
            """Process uploaded video clip"""
            if not self.access_token or not self.current_interview_id:
                logger.error("Missing access token or interview ID")
                return False

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.access_token}",
            }

            payload = {
                "interview_id": self.current_interview_id,
                "clip_id": clip_id,
                "uid": self.current_uid  # Use uid from create API here
            }

            with self.client.post(
                "/interviews-api/v1/interview/process/clip",
                json=payload,
                headers=headers,
                catch_response=True,
                name="/interview/process/clip"
            ) as response:
                if response.status_code == 200:
                    response_data = response.json()
                    if 'uid' in response_data:
                        self.current_uid = response_data['uid']
                    logger.info(f"Successfully processed video clip {clip_id}")
                    return True
                logger.error(f"Failed to process video clip {clip_id}: {response.status_code}")
                return False
            
#Hit_end_interview                

    def end_interview(self):
                """End the interview"""
                if not self.access_token or not self.current_interview_id:
                    logger.error("Missing access token or interview ID")
                    return False

                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                }

                payload = {
                    "interview_id": self.current_interview_id,
                    "uid": self.current_uid  # Include UID from create API if necessary
                }

                with self.client.post(
                    "/interviews-api/v1/interview/end",
                    json=payload,
                    headers=headers,
                    catch_response=True,
                    name="/interview/end"
                ) as response:
                    if response.status_code in [200, 204]:
                        logger.info(f"Successfully ended the interview: {self.current_interview_id}")
                        return True
                    logger.error(f"Failed to end interview: {response.status_code} - {response.text}")
                    return False


#Hit_duration_clip

    def duration_clip(self):
        """duration_clip"""
        if not self.access_token or not self.current_interview_id:
            logger.error("Missing access token or interview ID")
            return False

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            # "interview_id": self.current_interview_id,
            "uid": self.current_uid,  # Include UID from create API if necessary
            "clip_count": self.video_count,  
            "duration": self.video_count * 5
        }

        with self.client.post(
            "/interviews-api/v1/interview/duration-clip",
            json=payload,
            headers=headers,
            catch_response=True,
            name="/interview/duration-clip"
        ) as response:
            if response.status_code in [200, 204]:
                logger.info(f"Successfully called duration api: {response}")
                return True
            logger.error(f"duration api failed: {response.status_code} - {response.text}")
            return False
            

#Hit_interview_proccess
 
    def check_elevator_pitch_status(self):
            """Check the status of the elevator pitch until processed."""
            if not self.access_token:
                logger.error("Missing access token")
                return False

            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            current_interview_id = self.current_interview_id

            while True:
                dynamic_param = int(time.time() * 1000)

                # Construct the URL
                url = f"/interviews-api/v1/elevator-pitch/process-status?interview_id={current_interview_id}&_={dynamic_param}"
                logging.info(f"Constructed URL: {url}")

                with self.client.get(
                    url,
                    headers=headers,
                    catch_response=True,
                    name="/elevator-pitch/process-status"
                ) as response:
                    if response.status_code == 200:
                        response_data = response.json()
                        logger.info(f"Successfully retrieved elevator pitch status: {response_data}")

                        # Check for updated processing status
                        is_processed = response_data.get('is_processed', None)
                        video_status = response_data.get('video', 'not_created')
                        convert_video_status = response_data.get('convert_video', 'not_created')
                        is_skipped = response_data.get('is_skipped', 0)
                        video_percentage = response_data.get('video_clips_processed_percentage', 0)

                        # Log the key statuses
                        logger.info(f"Processing Status: {is_processed}")
                        logger.info(f"Video Status: {video_status}")
                        logger.info(f"Convert Video Status: {convert_video_status}")
                        logger.info(f"Is Skipped: {is_skipped}")
                        logger.info(f"Video Clips Processed Percentage: {video_percentage}%")

                        if is_processed == 1:
                            logger.info("Interview has been processed successfully.")
                            return True
                        elif is_processed == 0:
                            logger.info("Processing is still ongoing. Checking again...")
                        else:
                            logger.error(f"Unexpected processing status: {is_processed}. Exiting.")
                            return False  # Exit if status is unexpected
                    else:
                        logger.error(f"Failed to fetch elevator pitch status: {response.status_code} - {response.text}")
                        return False  # Stop on error

                # Wait before the next check
                time.sleep(5)  # Adjust the wait time as needed

                

            
