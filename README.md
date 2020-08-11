# LambProxy
HTTP Proxy using Amazon Lambda for source IP cycling

## Overview
This tool is a mitmproxy plugin that will intercept your HTTP/S requests and redirect them to an Amazon Lambda function. This way your request can be proxied through many IP addresses.

## Usage
    mitmproxy -p 8000 -s lambproxy.py --set roleArn='arn:aws:iam::123456789012:role/service-role/lambproxy-role-abcdefgh' --set maxWorkers=25
    
## Cleanup
Right now Lambproxy has a hard time cleaning up the lambda workers automatically when mitmproxy exits. You can clean them manually within the mitmproxy console like:

    :Lambproxy.cleanup
