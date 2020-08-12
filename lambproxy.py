# mitmproxy plugin to redirect requests to Lambda for IP source changing

from mitmproxy import http
from mitmproxy.net.http.http1.assemble import assemble_request
from mitmproxy.net.http.http1.read import read_response
from mitmproxy import ctx
from mitmproxy import command
import typing
import boto3
import base64
import json
import io
import sys
from http.client import HTTPResponse
import time

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
        self.role_arn = ""      # AWS role for lambda functions to use
        self.invocations = 0    # Keeping track of invocations becuase $$$

        self.scope = []         # Comma-separated list of URLs to match for scope
    

    # Add workers to Lambda
    def lambda_create_workers(self):
        for i in range(1, self.worker_max + 1):
            fn_name = self.worker_name + "_" + str(i)
            try:
                self.lambda_client.create_function(
                    FunctionName=fn_name,
                    Runtime='python3.8',
                    Role=self.role_arn,
                    Handler=f"{self.worker_name}.lambda_handler",
                    Code={'ZipFile': open(f"{self.worker_name}.zip", 'rb').read(), },
                    Timeout=3
                )
            except Exception as e:
                ctx.log.error("EXCEPTION: " + str(e))

        self.worker_count = self.count_lambda_workers()
        ctx.log.info(f"Created {self.worker_count} workers")


    # Delete all workers from Lambda
    def lambda_cleanup(self):
        w_count = self.count_lambda_workers()
        
        # Delete functions
        if w_count > 0:
            # Find all functions with self.worker_name_ prefix
            for function in self.lambda_client.list_functions()['Functions']:
                prefix = self.worker_name + "_"
                if prefix in function['FunctionName']:
                    self.lambda_client.delete_function(FunctionName=function['FunctionName'])


        # Update worker count locally
        self.worker_count = self.count_lambda_workers()
        ctx.log.info(f"{self.worker_count} workers left after cleanup")

    
    # Get number of worker functions currently in Lambda
    def count_lambda_workers(self):
        function_count = 0

        for function in self.lambda_client.list_functions()['Functions']:
            prefix = self.worker_name + "_"
            if prefix in function['FunctionName']:
                function_count = function_count + 1

        return function_count
    
    # Send request up to lambda function
    # data is a bytes object of base64 data
    def send_to_lambda(self, scheme, host, port, data):
        ctx.log.info("Sending to lambda")
        self.invocations = self.invocations + 1
        
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

        lambda_response = json.loads(response['Payload'].read().decode('utf-8'))

        # if "data" is not returned, something went wrong in Lambda
        if "data" in lambda_response:
            response_data = base64.b64decode(lambda_response['data'])
        else:
            response_data = f"<html><body><h1>Lambproxy ERROR</h1><br>".encode()
            ctx.log.error("Lambda response: " + str(lambda_response))
        return response_data

    
    # Every time a new request comes in, increment to the next worker
    # This is how the IP address changes with each request.
    def increment_worker(self):
        self.worker_current = self.worker_current + 1
        if self.worker_current > self.worker_max:
            self.worker_current = 1
    

    # Returns True if a URL is in the scope list
    def in_scope(self, url):
        for scope_item in self.scope:
            if scope_item in url:
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
            name = "maxWorkers",
            typespec = typing.Optional[int],
            default = 1,
            help = "Set max number of Lambda workers"
        )
        
    # Called whenever the configuration changes
    def configure(self, updates):
        if "maxWorkers" in updates:
            self.worker_max = int(ctx.options.maxWorkers)
            ctx.log.info("Max workers set to " + str(self.worker_max))
        
        if "scope" in updates:
            scope_items = str(ctx.options.scope).split(',')
            for item in scope_items:
                self.scope.append(item)
            ctx.log.info("Scope: " + str(self.scope))
        
        if "roleArn" in updates:
            ctx.log.info("Cleaning up lambda workers...")
            self.lambda_cleanup()

            self.role_arn = str(ctx.options.roleArn)
            ctx.log.info("Role ARN set: " + self.role_arn)

            ctx.log.info("Creating lambda workers...")
            self.lambda_create_workers()

    # Called when addon shuts down. Logging is disabled by this point.
    def done(self):
        ctx.log.info("Cleaning up lambda workers")
        self.lambda_cleanup()
        ctx.log.info("Done")
    
    # Called each time a new request comes in
    def request(self, flow: http.HTTPFlow) -> None:       
        # Only redirect to Lambda if the URL is in scope
        
        if not self.in_scope(flow.request.pretty_url):
            return

        # Cycle to next worker/IP
        self.increment_worker()

        ctx.log.info(f"URL {flow.request.pretty_url} is in scope")

        # Pull info from request
        host = flow.request.pretty_host
        port = flow.request.port
        scheme = flow.request.scheme
        data = base64.b64encode(assemble_request(flow.request))  

        # Send request to lambda
        response = self.send_to_lambda(scheme, host, port, data)

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
        
addons = [Lambproxy()]