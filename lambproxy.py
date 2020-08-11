import socket
import threading
import signal
import sys
import base64
import boto3
import json

class LambdaServer(object):
    def __init__(self, port=8000):
        #Local proxy info
        self.host = "127.0.0.1"
        self.port = port
        self.conn_established = False

        # Upstream server info
        self.upstream_host = ""
        self.upstream_port = 0

        # Lambda info
        self.lambda_client = boto3.client('lambda')
        self.worker_name = "lambproxy"  # Name of lambda function
        self.worker_current = 0         # Keep track of which worker was last used


    def handle_request(self, client_socket):
        while True:
            print("----- Loop begin -----")
            response = b"HTTP/1.1 404 Not Found\r\n"
            data = client_socket.recv(4096) #.decode()
            #print("DEBUG: data: " + data.decode())

            # No data received
            #if not data: break

            https = False
            # If this works, then it's likely plaintext
            try: 
                line1 = data.decode().split('\n')[0]
            except:
                https = True

            # If connection is plaintext
            #if self.conn_established == False:
            if "HTTP" in line1:
            #if not self.conn_established:
                print("DEBUG: line1:" + line1)
                request_method = line1.split(' ')[0]

                # HTTPS connections use CONNECT, HTTP connections don't
                if request_method == "CONNECT":
                    print("DEBUG: CONNECT received")
                    self.upstream_host = line1.split(' ')[1].split(':')[0]
                    self.upstream_port = int(line1.split(' ')[1].split(':')[1])
                    response = b"HTTP/1.0 200 Connection Established\r\n\r\n"  # Update later to ensure remote server is actually available
                    self.conn_established = True
                else:
                    print("DEBUG: Other method received")
                    self.upstream_host = line1.split('/')[2]
                    self.upstream_port = 80
                    response = self.forward_request(base64.b64encode(data))
                line1 = ""
            else:
                print("DEBUG: Encrypted traffic detected")
                response = self.forward_request(base64.b64encode(data))

                print("DEBUG: Forwarding message to browser")
            client_socket.send(response)
            #client_socket.close()
            #break
                
        #client_socket.close()        

    def forward_request(self, data):
        print("DEBUG: Forwarding request to Lambda...")
        print("Host: " + self.upstream_host)
        print("Port: " + str(self.upstream_port))
        print("Data: " + data.decode('UTF-8'))
        
        response_data = b"HTTP/1.1 404 Not Found\r\n"    # Default response

        '''
        # Send request up to lambda function
        response = self.lambda_client.invoke(
            #FunctionName=f'{self.worker_name}_{self.worker_current}',
            FunctionName=f'{self.worker_name}',
            InvocationType='RequestResponse',
            Payload=json.dumps(dict({'host': self.upstream_host, 'port': self.upstream_port, 'data': data.decode('ascii')}))
        )
        
        
        lambda_response = json.loads(response['Payload'].read().decode('utf-8'))
        print("DEBUG: Message received from lambda:")
        print(str(lambda_response))
        if "data" in lambda_response:
            response_data = base64.b64decode(lambda_response['data'])
            #print("\t" + base64.b64decode(lambda_response['data']).hex())
        else:
            print("ERROR in lambda response: " + str(lambda_response))
        '''

        # debug stuff
        s = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        socket.setdefaulttimeout(10)
        s.connect((self.upstream_host,self.upstream_port))
        s.send(base64.b64decode(data))
        response_data = s.recv(4096)

        print("Response Data: " + response_data.hex())

        return response_data

    # Start up proxy server
    def start(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind((self.host, self.port))
        self.listen()

    # Gracefully shut down the socket
    def shutdown(self):
        self.socket.shutdown(socket.SHUT_RDWR)

    # Tell socket to listen for incomming connections
    def listen(self):
        self.socket.listen(5)
        while True:
            (client, address) = self.socket.accept()
            client.settimeout(60)
            threading.Thread(target=self.handle_request, args=([client])).start()
    
def shutdownServer(sig, unused):
    """
    Shutsdown server from a SIGINT recieved signal
    """
    server.shutdown()
    sys.exit(1)

signal.signal(signal.SIGINT, shutdownServer)
server = LambdaServer(8000)
server.start()
print("Press Ctrl+C to shut down server.")


