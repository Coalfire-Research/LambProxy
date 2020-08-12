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
    response = b''
    while True:
        recv = s.recv(1024)
        if not recv:
            break
        response += recv
    return base64.b64encode(response)
   
def forward_https_request(host, port, data):
    context = ssl.create_default_context()
    s = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    ssock = context.wrap_socket(s, server_hostname=host)
    socket.setdefaulttimeout(10)
    ssock.connect((host,port))
    ssock.send(data)
    response = b''
    while True:
        recv = ssock.recv(1024)
        if not recv:
            break
        response += recv
    return base64.b64encode(response)

def lambda_handler(event, context):
    scheme = event['scheme']
    host = event['host']
    port = int(event['port'])
    data = base64.b64decode(event['data'])

    if scheme == "https":
        result = forward_https_request(host, port, data)
    else:
        result = forward_http_request(host, port, data)
    
    return {
        'statusCode': 200,
        'data': result.decode('ascii')
    }
    