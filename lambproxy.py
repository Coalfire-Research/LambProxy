# mitmproxy plugin to redirect requests to Lambda for IP source changing

from mitmproxy import http
from mitmproxy.net.http.http1.assemble import assemble_request
from mitmproxy.net.http.http1.read import read_response
from mitmproxy import ctx
from mitmproxy import command
from mitmproxy import exceptions
import typing
import boto3
import base64
import json
import io
import sys
from http.client import HTTPResponse
import time
import zipfile
import collections
import requests

# Converts raw HTTP response data into stream object so it can be processed by http.client
class FakeSocket():
    def __init__(self, response_bytes):
        self._file = io.BytesIO(response_bytes)
    def makefile(self, *args, **kwargs):
        return self._file


# All the good stuff happens in this class
class Lambproxy:
    def __init__(self) -> None:
        self.worker_name = "lambproxy"
        self.worker_max = 1     # Max number of lambda functions
        self.worker_current = 1 # Keep track of which Lambda worker was the last used
        self.worker_count = 0   # Keeping track of the number of functions within Lambda

        self.lambda_client = boto3.client('lambda')
        self.regions = []               # List of enabled AWS regions
        self.accessible_regions = []    # List of regions accessible to the aws account
        self.first_region = ""          # Keep track of original first region in list
        self.role_arn = ""              # AWS role for lambda functions to use
        self.invocations = 0            # Keeping track of invocations becuase $$$
        self.invocations_max = None     # Can set max invocations to save $$$

        self.scope = []         # Comma-separated list of URLs to match for scope

        self.burn_trigger = None        # If this string is in the response, consider the worker's IP burned
    
    # Load worker python script and create zip file for Lambda upload
    ###############################
    def zip_worker(self):
        # Create zip file in memory
        z = io.BytesIO()
        zipf = zipfile.ZipFile(z, 'w')

        # Worker file scripy name
        worker_file = f"{self.worker_name}_worker.py"

        # Add worker script to zip file
        zipf.write(worker_file)
        zipf.close()
        return z.getvalue()


    # Worker IP is burned. Destroy it and recreate it
    ###############################
    def burn_worker(self):
        fn_name = f"{self.worker_name}_{self.worker_current}"
        ctx.log.warn(f"Worker_{self.worker_current} is burned. Rebuilding...")
        # Current worker is burned, destroy it
        self.lambda_client.delete_function(FunctionName=fn_name)
        self.lambda_create_function(fn_name)


    # Actually create a single lambda function
    ###############################
    def lambda_create_function(self, fn_name):
        try:
            self.lambda_client.create_function(
                FunctionName=fn_name,
                Runtime='python3.8',
                Role=self.role_arn,
                Handler=f"{self.worker_name}_worker.lambda_handler",
                Code={'ZipFile': self.zip_worker()},
                Timeout=10
            )
        except Exception as e:
            ctx.log.error("CreateWorker EXCEPTION: " + str(e))

    # Add workers to Lambda
    ###############################
    def lambda_create_workers(self):
        for i in range(1, self.worker_max + 1):
            fn_name = self.worker_name + "_" + str(i)
            self.lambda_create_function(fn_name)
            self.increment_worker()
        self.worker_count = self.count_lambda_workers()
        ctx.log.info(f"Created {self.worker_count} workers")


    # Delete all workers from specified Lambda regions
    ###############################
    def lambda_cleanup(self):
        w_count = 0
        try:
            w_count = self.count_lambda_workers()
        except Exception as e:
            ctx.log.error("Exception " + str(e))

        # Delete functions
        if w_count > 0:
            # Delete in all configured regions
            for region in self.regions:
                lambda_client = boto3.client('lambda', region)
                # Find all functions with self.worker_name_ prefix
                for function in lambda_client.list_functions()['Functions']:
                    prefix = self.worker_name + "_"
                    if prefix in function['FunctionName']:
                        try:
                            lambda_client.delete_function(FunctionName=function['FunctionName'])
                        except Exception as e:
                            ctx.log.error("EXCEPTION: Could not delete lambda function: " + str(e))

        # Update worker count locally
        self.worker_count = self.count_lambda_workers()
        ctx.log.info(f"{self.worker_count} workers left after cleanup")

     
    # Get number of worker functions currently in Lambda
    ###############################
    def count_lambda_workers(self):
        function_count = 0
        for region in self.regions:
            lambda_client = boto3.client('lambda', region)
            try:
                fn_list = lambda_client.list_functions()['Functions']
            except Exception as e:
                ctx.log.error("EXCEPTION: " + str(e))
            for function in fn_list:
                prefix = self.worker_name + "_"
                if prefix in function['FunctionName']:
                    function_count = function_count + 1

        return function_count
    

    # Send request up to lambda function
    # data is a bytes object of base64 data
    ###############################
    def send_to_lambda(self, scheme, host, port, data):
        ctx.log.info("Sending to lambda")

        # Keep track of total invocations
        self.invocations = self.invocations + 1
        
        # Invoke Lambda worker function
        response = self.lambda_client.invoke(
            FunctionName=f'{self.worker_name}_{self.worker_current}',
            InvocationType='RequestResponse',
            Payload=json.dumps(dict({
                'scheme': scheme,
                'host': host, 
                'port': port, 
                'data': data.decode('ascii')
                }))
        )
        
        lambda_response = json.loads(response['Payload'].read().decode('ascii'))
        ctx.log.debug(lambda_response)

        # if "data" is not returned, something went wrong in Lambda
        if "data" in lambda_response:
            response_data = base64.b64decode(lambda_response['data'])
        else:
            response_data = f"HTTP/1.1 500 Server Error\r\n\r\n<html><body><h1>Lambproxy ERROR</h1><br>{str(lambda_response)}\r\n\r\n".encode()
            ctx.log.error("Lambda response: " + str(lambda_response))

        # Cycle to next worker/IP
        self.increment_worker()

        return response_data

    
    # Every time a new request comes in, increment to the next worker
    # This is how the IP address changes with each request.
    ###############################
    def increment_worker(self):
        self.worker_current = self.worker_current + 1
        # Also shift the region list so we move to a different region with each request
        self.rotate_regions()

        # If we reached the last worker, start over and reset the region to the original region
        if self.worker_current > self.worker_max:
            self.worker_current = 1
            # Reset region back to the first one
            while self.regions[0] != self.first_region:
                self.rotate_regions()

    
    # This function rotates the list of regions to ensure we always hit a new one
    ###############################
    def rotate_regions(self):
        try:
            region_collection = collections.deque(self.regions)
            region_collection.rotate(1)
            self.regions = list(region_collection)
        except Exception as e:
            ctx.log.error("EXCEPTION rotating regions: " + str(e))
        self.lambda_client = boto3.client('lambda', self.regions[0])
        

    # Returns True if a URL is in the scope list
    ###############################
    def in_scope(self, url):
        for scope_item in self.scope:
            if scope_item in url:
                return True
        return False

    # Test a region to see if it's enabled
    ##############################
    def test_region(self, region):
        sts = boto3.client('sts', region_name=region)
        try:
            sts.get_caller_identity()
        except:
            return False
        return True

    # Build a list of regions accessible to the AWS account
    ###############################
    def find_accessible_regions(self):
        # Get list of all regions from AWS
        try:
            all_regions = boto3.session.Session().get_available_regions('lambda')
        except:
            ctx.log.error("EXCEPTION: " + e)
        
        # Test all regions. Some regions must be specifically enabled in your AWS account
        v_regions = []
        for region in all_regions:
            if self.test_region(region):
                v_regions.append(region)
            
        return v_regions

    # Check upstream response to see if trigger was hit
    ###############################
    def check_trigger(self, response):
        #ctx.log.info("response: " + response.decode('UTF-8'))
        if self.burn_trigger:
            if self.burn_trigger in response.decode('UTF-8'):
                return True
        return False

    #############################
    # Handle MITMPROXY Commands
    #############################
    @command.command("Lambproxy.setRoleArn")
    def setRoleArn(self, roleArn: str):
        self.roleArn = roleArn
        ctx.log.info("Role ARN set")

    @command.command("Lambproxy.createWorkers")
    def createWorkers(self):
        ctx.log.info("Creating lambda workers...")
        self.lambda_create_workers()

    @command.command("Lambproxy.cleanup")
    def cleanup(self):
        ctx.log.info("Removing lambda workers...")
        self.lambda_cleanup()


    #############################
    # Handle MITMPROXY Events
    #############################

    # Called when plugin is first loaded
    ###############################
    def load(self, loader):
        loader.add_option(
            name = "roleArn",
            typespec = typing.Optional[str],
            default = "",
            help = "Set AWS Lambda role ARN"
        )
        
        loader.add_option(
            name = "scope",
            typespec = typing.Optional[str],
            default = "",
            help = "Comma-separated list of URLs that are in-scope for Lambda processing"
        )
        
        loader.add_option(
            name = "regions",
            typespec = typing.Optional[str],
            default = "",
            help = "Comma-separated list of AWS regions for Lambda functions"
        )
        
        loader.add_option(
            name = "maxWorkers",
            typespec = typing.Optional[int],
            default = 1,
            help = "Set max number of Lambda workers"
        )

        loader.add_option(
            name = "maxInvocations",
            typespec = typing.Optional[int],
            default = None,
            help = "Set max number of Lambda invocations"
        )

        loader.add_option(
            name = "trigger",
            typespec = typing.Optional[str],
            default = None,
            help = "Set burn trigger string"
        )
        
        
    # Called whenever the configuration changes
    ###############################
    def configure(self, updates):
        if "regions" in updates:
            regions = str(ctx.options.regions).lower().replace(' ','').split(',')

            # Build list of regions this account is able to access
            #self.accessible_regions = self.find_accessible_regions()
            
            # Ensure entered regions are valid
            for region in regions:
                if self.test_region(region):
                    self.regions.append(region)
                else:
                    raise exceptions.OptionsError(f"Invalid region '{region}'")
            self.first_region = self.regions[0]
        ctx.log.info("Configured regions: " + str(self.regions))
        
        if "roleArn" in updates:
            self.role_arn = str(ctx.options.roleArn)
            # Check for empty Role ARN
            if self.role_arn == "":
                raise exceptions.OptionsError("No roleArn specified!")

        ctx.log.info("Configured Role ARN: " + self.role_arn)

        if "maxWorkers" in updates:
            self.worker_max = int(ctx.options.maxWorkers)
        ctx.log.info("Configured max workers: " + str(self.worker_max))

        if "scope" in updates:
            # Check for empty scope
            if str(ctx.options.scope) == "":
                raise exceptions.OptionsError("No scope specified!")

            scope_items = str(ctx.options.scope).lower().replace(' ','').split(',')
            for item in scope_items:
                self.scope.append(item)
        ctx.log.info("Configured scope: " + str(self.scope)) 

        if "maxInvocations" in updates:
            try:
                self.invocations_max = int(ctx.options.maxInvocations)
            except:
                self.invocations_max = None
        ctx.log.info("Configured max invocations: " + str(self.invocations_max))
        
        if "trigger" in updates:
            try:
                self.burn_trigger = str(ctx.options.trigger)
            except:
                self.burn_trigger = None
            if self.burn_trigger == "":
                self.burn_trigger = None
        
        ctx.log.info("Configured trigger: " + self.burn_trigger)
        
        ctx.log.info("Cleaning up old lambda workers...")
        self.lambda_cleanup()
        ctx.log.info("Creating new lambda workers...")
        self.lambda_create_workers()
       

    # Called when addon shuts down. Logging is disabled by this point.
    ###############################
    def done(self):
        ctx.log.info("Cleaning up lambda workers")
        self.lambda_cleanup()
        ctx.log.info("Done")
    
    # Called each time a new request comes in
    # This is essentialy the main loop
    ###############################
    def request(self, flow: http.HTTPFlow) -> None:       

        # If invocation limit is set, then check it first to save $$$
        if self.invocations_max:
            if self.invocations >= self.invocations_max:
                ctx.log.info("Max Lambda invocations exceeded. Skipping.")
                return

        # Only redirect to Lambda if the URL is in scope
        if not self.in_scope(flow.request.pretty_url):
            return

        ctx.log.info(f"URL {flow.request.pretty_url} is in scope")

        # Pull info from request
        host = flow.request.pretty_host
        port = flow.request.port
        scheme = flow.request.scheme

        data = base64.b64encode(assemble_request(flow.request))  
        ctx.log.debug("Request: " + data.decode('utf-8'))
        
        while True:
            # Send request to lambda
            response = self.send_to_lambda(scheme, host, port, data)

            # If trigger string is hit, rebuild worker and send again
            if self.check_trigger(response):
                self.burn_worker()
                continue
            break

        # Helps parse headers from the response
        source = FakeSocket(response)
        r = HTTPResponse(source)
        r.begin()

        # Convert headers to bytes
        headers = []
        for h in r.getheaders():
            headers.append((h[0].encode(), h[1].encode()))

        # Make response object to send back to browser
        flow.response = http.HTTPResponse.make(
            r.status,  # (optional) status code
            r.read(len(response)),  # (optional) content
            headers
        )
        
        ctx.log.info("Lambda invocations: " + str(self.invocations) + "\n")

# Register addon 
addons = [Lambproxy()]