# LambProxy
HTTP Proxy using Amazon Lambda for source IP cycling

## Overview
This tool is a mitmproxy plugin that will intercept your HTTP/S requests and redirect them to an Amazon Lambda function. This way your request can be proxied through many IP addresses.

## Usage
Thus plugin takes a number of arguments.

    roleArn           - Required - The AWS ARN for your Lambda Role. Create this in IAM.
    scope             - Required - Comma-separated list of in-scope URLs.
    maxWorkers        - Optional - Integer specifying the number of Lambda workers to spin up. Default is 1.
    maxInvocations    - Optional - Requests will not be forwarded to Lambda after this number is reached.
    regions           - Optional - Comma-separated list of AWS regions to cycle for each request. Default is all supported regions.
    trigger           - Optional - If this string shows up in the response, your IP is considered burned. Lambproxy rebuilds that worker and resends the request automatically.

## Example
    mitmproxy -p 8000 -s lambproxy.py --set scope='http://api.ipify.org,https://api.ipify.org' --set roleArn='arn:aws:iam::123456789012:role/service-role/lambproxy-role-abcdefgh' --set maxWorkers=10 --set regions='us-west-1,us-west-2,us-east-1'

![Example 1](/screenshots/Lambproxy1.png?raw=true "Different IP returned from ipify.org with each request")

![Example 2](/screenshots/Lambproxy2.png?raw=true "Invocation limit exceeded")

## Prerequisites
Lambproxy will create Lambda functions within your AWS account. Therefore, it will require limited access to an AWS account in order to function properly. Lambproxy relies on Boto3 for AWS authentication. AWS access keys can be placed in environment variables, a credential file, etc as permitted by Boto3. Newly created Lambda functions will require an execution role. Below is a basic working exeecution role template. This role gives the Lambda functions access to the defined AWS resources. Your user account does not need this access.

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

Lambproxy must be run as a user with access to four Lambda permissions and two IAM permissions. The below policy template can be applied to your Lambproxy user account to provide it with minimal working permissions.

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
A "Worker" is a Lambda function that acts as an HTTP/S proxy. Each worker has a chance of obtaining its own unique IP address. Each worker's IP address is set automatically by AWS when the function is invoked, though in practice each worker tends to have the same IP address with multiple invocations. Therefore, the more workers you have, the higher chance you will have a larger number of unique source IPs. It is possible for multiple workers to have the same source iP address as a coincidence. Lambproxy will create workers with the name "lambproxy_X" where X is a number 1 through (maxWorkers). Every time a new request comes in, Lambproxy will cycle to the next worker in the next region. When it reaches the maxmimum number then it cycles back to one.

## Scope
You can specify as many scope items as you like. Scoping is not strict, but you can be more restrictive by specifying directories and subdirectories. If no scope is specified then all URLs are in-scope.

### Scope Examples
    scope='http://www.foo.com/'                     - Matches http://www.foo.com/*
    scope='http://www.foo.com/test/only/here'       - Matches http://www.goo.com/test/only/here*
    scope='https://www.foo.com,https://www.foo.com' - Matches HTTP and HTTPS traffic for www.foo.com
    scope='http'                                    - Matches any URL containing "http" (all URLs)
    
## Cleanup
Lambproxy has a hard time cleaning up the lambda workers automatically when mitmproxy exits. You can clean them manually within the mitmproxy console by issuing the Lambproxy.cleanup command. This command searches Lambda for for al functions matching "lambscan_x" where x is an integer. All matching functions will be deleted.

    :Lambproxy.cleanup

## Caveats
- Lambproxy is slow. It can take 2-3 seconds for a Lambda function to execute and return, which introduces delay to your HTTP request.
- This tool fails open, so don't expect it to hide your real IP from a given target. This is not a privacy tool.
- This tool probably breaks the AWS Acceptable Use Policy.

## How it works
1. mitmproxy intercepts (and decrypts, if necessary) HTTP/S traffic.
2. If the URL is out of scope, it is forwarded along to the destination as normal.
3. If the URL is in scope, the entire raw request is base64 encoded.
4. The lambda worker is then invoked with the encoded request sent as part of the Lambda event payload.
5. The lambda worker then opens a socket to the host on the specified port (using TLS if needed).
6. The lambda worker decodes the request and forwards it to the destination server via the socket.
7. The lambda worker receives a response, base64 encodes it, and returns this value to mitmproxy.
8. Lambproxy decodes the response and parses it to build a mitmproxy HTTPResponse object it can then return to the browser.
