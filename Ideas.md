# Ideas

- Lambproxy is pretty slow right now. It takes around 3 seconds to get a reply from the lambda function. Even just a blank function that simply returns without doing anything takes 2-3 seconds to execute. How can this be sped up?
  - Maybe the workers can be spun up ahead of time and listening on a reverse socket so they are ready to go? This is less efficient and more expensive though.
  - What if Lambproxy waits until it receives an in-scope request, then it spins up long-running workers with a socket connected? It starts a timer and if it doen't receive an in-scope request in some amount of time, it kills the functions. The initial request will be delayed but the rest should be fine as long as the delay isn't too long between requests.


