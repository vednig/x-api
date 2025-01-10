# x-api
Unofficial X API using Selenium and FastApi

## How to Run in Development 
1. Create a virtual env using module `virtualenv`

``` virtualenv dev ```

2. Activate Virtual Env (if you don't know google this and add your OS type)

3. Install dependencies using 

`pip install -r requirements.txt`

4. Run App

`python ./src/main.py`

**Note: To run in production use WSGI or ASGI servers**

# Features & Roadmap
- Currently API returns only the required contents for particular person(a.k.a the author) in whole thread as required for [Unlaceapp](https://github.com/vednig/unlaceapp)
- Additional Requests can also be added, to provide compatibility with X official API upon request and usecase

## Debugging/Errors
If you're facing error or issues during build open up an issue.

If you've ideas or want to open PR please create an issue first.
