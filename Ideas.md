# Ideas

## Process
- Write a listening HTTP Server
- Take the request, serialize and send to Lambda
- Lambda uses requests library to make the request
- Lambda serializes the response and sends it back
- Client software then spits that out as the HTTP request

## Problems
- Though HTTP seems to be working, HTTPS is not. Maybe something to do with the TCP connection getting broken up?
- Maybe have lambproxy listen only for HTTP requests, but with a specil header it knows to make it HTTPS. Then it just tells lambda to make the request for you and send the results back. So the browser always thinks it's HTTP, but really the end connection is HTTPS?


