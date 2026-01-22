from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=5)

def run_bg(func, *args):
    executor.submit(func, *args)
