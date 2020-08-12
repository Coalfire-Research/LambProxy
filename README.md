# LambProxy
HTTP Proxy using Amazon Lambda for source IP cycling

## Overview
This tool is a mitmproxy plugin that will intercept your HTTP/S requests and redirect them to an Amazon Lambda function. This way your request can be proxied through many IP addresses.

## Usage
Thus plugin takes a number of arguments.
- roleArn       - Required - The AWS ARN for your Lambda Role. Create this in IAM.
- scope         - Required - A comma-separated list of in-scope URLs.
- maxWorkers    - Optional - Integer specifying the number of Lambda workers to spin up. Default is 1.

## Example
    mitmproxy -p 8000 -s lambproxy.py --set scope='http://api.ipify.org,https://api.ipify.org' --set roleArn='arn:aws:iam::123456789012:role/service-role/lambproxy-role-abcdefgh' --set maxWorkers=25

## Prerequisites
Lambproxy will create Lambda functions within your AWS account. Therefore, it will require limited access to an AWS account in order to function properly. Lambproxy relies on Boto3 for AWS authentication. AWS access keys can be placed in environment variables, a credential file, or more as permitted by Boto3. Newly created Lambda functions will require an execution role. Below is a basic working exeecution role template. This role will be applied to the Lambda functions directly. Your user account does not need this access.

    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "logs:CreateLogGroup",
                "Resource": "arn:aws:logs:*:123456789012:*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                "Resource": [
                    "arn:aws:logs:*:123456789012:log-group:/aws/lambda/lambproxy:*"
                ]
            }
        ]
    }

Lambproxy requires a user with access to four Lambda permissions and two IAM permissions. The below policy template can be applied to your Lambproxy user account to provide it with minimal working permissions.

    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "lambda:CreateFunction",
                    "lambda:InvokeFunction",
                    "lambda:DeleteFunction"
                ],
                "Resource": "arn:aws:lambda:*:123456789012:function:lambproxy_*"
            },
            {
                "Effect": "Allow",
                "Action": "lambda:ListFunctions",
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "iam:GetRole",
                    "iam:PassRole"
                ],
                "Resource": "arn:aws:iam::123456789012:role/service-role/lambproxy-role-abcdefgh"
            }
        ]
    }

## Workers
A "Worker" is a Lambda function that acts as an HTTP/S proxy. Each worker has a chance of obtaining its own unique IP address from the other workers. A source IP address is chosen at random by AWS when you function is invoked, though in practice each worker tends to have the same IP address with multiple invocations. Therefore, the more workers you have, the higher chance you will have a larger number of unique source IPs. Lambproxy will create workers with the name "lambproxy_X" where X is a number 0 through (maxWorkers - 1). Every time a new request comes in, Lambproxy will cycle to the next worker. When it reached the maxmimum number then it cycles back to zero.

## Scope
You can specify as many scope objects as you like. Scoping is not strict, but you can be more restrictive by specifying directories and subdirectories.

### Scope Examples
    scope='http://www.foo.com/'                     - Matches http://www.foo.com/*
    scope='http://www.foo.com/test/only/here'       - Matches http://www.goo.com/test/only/here*
    scope='https://www.foo.com,https://www.foo.com' - Matches HTTP and HTTPS traffic for www.foo.com
    scope='http'                                    - Matches any URL containing "http" (all URLs)
    
## Cleanup
Lambproxy has a hard time cleaning up the lambda workers automatically when mitmproxy exits. You can clean them manually within the mitmproxy console by issueing the Lambproxy.cleanup command. This command searches Lambda for for al functions matching the "lambscan_x" where x is an integer. All matching functions will be deleted.

    :Lambproxy.cleanup

## How it works
1. mitmproxy intercepts (and decrypts, if necessary) HTTP/S traffic
1. If the URL is in scope, the entire raw request is base64 encoded
1. The lambda worker is then invoked with the request sent as part of the event data
1. The lambda worker then opens a socket to the host on the specified port (using TLS if needed)
1. The lambda worker decodes the request and forwards it to the destination server
1. The lambda worker receives a response, base64 encodes it, and returns this value
1. Lambproxy decodes the response and parses it to build a mitmproxy HTTPResponse object it can return to the browser
