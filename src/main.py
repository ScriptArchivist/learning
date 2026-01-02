#from fastapi import FastAPI

#app = FastAPI()

#@app.get("/")
#def top():
#    return "top here"

#@app.get("/echo/{thing}")
#def echo(thing):
#    return f"echoing {thing}"

#if __name__ == "__name__":
#    import uvicorn
#    uvicorn.run("main:app", reload=True)


from fastapi import FastAPI
from web import explorer

app = FastAPI()

app.include_router(explorer.router)