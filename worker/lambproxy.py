#!/usr/bin/python
import json
import socket
import base64

def forward_request(host, port, data):
   s = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
   socket.setdefaulttimeout(5)
   s.connect((host,port))
   s.send(data)
   response = client.recv(4096)
   return base64.b64encode(response)

def lambda_handler(event, context):
    host = event['host']
    port = event['port']
    data = base64.b64decode(event['data'])
    
    result = forward_request(host, proto, port)
    
    return {
        'statusCode': 200,
        'data': result
    }