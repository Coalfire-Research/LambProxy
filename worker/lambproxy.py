#!/usr/bin/python
import json
import socket
import base64
import ssl

def forward_http_request(host, port, data):
   s = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
   socket.setdefaulttimeout(10)
   s.connect((host,port))
   s.send(data)
   response = s.recv(4096)
   return base64.b64encode(response).decode('ascii')
   
def forward_https_request(host, port, data):
   context = ssl.create_default_context()
   s = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
   ssock = context.wrap_socket(s, server_hostname=host)
   socket.setdefaulttimeout(10)
   ssock.connect((host,port))
   ssock.send(data)
   response = ssock.recv(4096)
   return base64.b64encode(response).decode('UTF-8')

def lambda_handler(event, context):
    host = event['host']
    port = int(event['port'])
    data = base64.b64decode(event['data'])
    
    if port == 443:
        result = forward_https_request(host, port, data)
    else:
        result = forward_http_request(host, port, data)
    
    return {
        'statusCode': 200,
        'data': result
    }
    