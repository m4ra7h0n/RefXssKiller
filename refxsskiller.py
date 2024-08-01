import asyncio
import re
import sys
import time

import aiohttp
from multiprocessing import Pool, cpu_count, Process, Manager, Lock
from urllib.parse import urlparse, parse_qs, quote, urlencode

class ProcessBar:
    def __init__(self, manager, total=0):
        self.lock = manager.Lock()
        self.start = manager.Value('d', time.perf_counter())
        self.data = manager.Value('i', 0)
        self.counter = manager.Value('i', 0)
        self.total = manager.Value('i', total)
        self.success = manager.Value('i', 0)
        self.fail = manager.Value('i', 0)
        self.died = manager.Value('i', 0)

    def set_total(self, total):
        with self.lock:
            self.total.value = total

    def print_accumulator(self, data, died, success, fail, header='Xss progress'):
        with self.lock:
            total = self.total.value
            dur = time.perf_counter() - self.start.value
            self.data.value += data
            self.counter.value += 1
            self.success.value += success
            self.fail.value += fail
            self.died.value += died
            bar_n = int((self.data.value / total) * 50)
            h, remainder = divmod(dur, 60 * 60)
            m, s = divmod(remainder, 60)
            l_h, l_remainder = divmod(
                (int(total / (data if data > 0 else 1)) - self.counter.value) * (dur / self.counter.value),
                60 * 60)
            l_m, l_s = divmod(l_remainder, 60)
            print(
                "\r{header}: {percent:^3.0f}% ({now}/{total}) : {bar}{underline}  {h:02d}:{m:02d}:{s:02d} (预计剩余:{l_h:02d}:{l_m:02d}:{l_s:02d}) (died:{died}, success:{success}, fail:{fail})".format(
                    header=header,
                    percent=int((self.data.value / total) * 100),
                    total=total, now=self.data.value,
                    died=self.died.value, success=self.success.value, fail=self.fail.value,
                    bar="▋" * bar_n,
                    underline="_" * (50 - bar_n),
                    h=int(h), m=int(m), s=int(s),
                    l_h=int(l_h), l_m=int(l_m), l_s=int(l_s)),
                end="")
            sys.stdout.flush()
            time.sleep(0.05)


# 生成参数
def generate_params(payload, n, parameters):
    try:
        out = []
        for num, key in enumerate(parameters, start=1):
            encoded_value = quote(f"{payload}{(num - 1) % n + 1}")
            encoded_key = quote(key, safe='')
            out.append(f"{encoded_key}={encoded_value}")
            if num % n == 0:
                yield '&'.join(out)
                out.clear()
        if out:
            yield '&'.join(out)

    except Exception as e:
        print(f"An error occurred: {e}")


def handle_response(url, resp, payload_verifier, reflected_url, proxy):
    pattern = '|'.join(payload_verifier)
    if re.search(pattern, resp):  # 大部分没有反射, 使用re.search过滤效率高
        # 这个reflected_url是一个map, 因为比如反射lol123会有很多, 每个url只输出一次就可以了
        if reflected_url.get(url) is None:
            reflected_url[url] = set()
        for payload in payload_verifier:
            if payload in resp and payload not in reflected_url[url]:
                reflected_url[url].add(payload)
                print(f"\n\n\n\nKeyword {payload} found in the response for URL: {url}\n\nUses proxy: {proxy}\n\nResponse: {resp}")


# 用于发送 GET 请求的异步函数
async def fetch(session, url, payload_verifier, reflected_url, timeout=5, proxy=None):
    retries = 1  # 设置重试次数
    while retries > 0:
        try:
            async with session.get(url, proxy=proxy) as response:
                text = await response.text()
                handle_response(url, text, payload_verifier, reflected_url, proxy)
                return True
        except asyncio.TimeoutError:
            retries -= 1
            if retries == 0:
                # print(f"Timeout after {timeout} seconds for {url}.")
                return False
        except Exception as e:
            retries -= 1
            # print(f"Error fetching {url}: {e}")
            if retries == 0:
                return False


def replace_query_values(url, replacement):
    # 解析URL
    parsed_url = urlparse(url)
    # 获取查询参数
    query_params = parse_qs(parsed_url.query)
    # 替换所有参数的值
    for key in query_params:
        query_params[key] = [replacement]
    # 重新构建查询字符串
    new_query = urlencode(query_params, doseq=True)
    # 构建新的URL
    new_url = parsed_url._replace(query=new_query).geturl()
    return new_url


def handle_parameters(url, param_set):
    return f'{url}&{param_set}' if '?' in url else f'{url}?{param_set}'

async def is_url_reachable(session, url):
    """
    尝试访问给定的 URL 并检查是否可达到。
    如果 URL 可达，则返回 True；否则返回 False。
    """
    try:
        async with session.get(url, timeout=5) as response:
            # 无论响应状态如何，只要成功返回响应，我们就认为它是可达的
            return True
    except (aiohttp.ClientError, asyncio.TimeoutError):
        # 捕获任何异常，比如连接失败或超时
        return False
async def get_proxy(proxy_pool):
    if not proxy_pool:
        return None
    url = "http://127.0.0.1:5010/get/"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                return 'http://' + data['proxy']
    except Exception as e:
        print(f'proxy_pool: {e}')
        return None

# 异步函数，用于处理一组 URL
async def process_urls(urls, params, each_req_param_num, payload, payload_verifier, proxy_pool):
    async with aiohttp.ClientSession() as session:
        tasks = []
        reflected_url = {}
        unreachable = 0

        for url in urls:
            # 检查 URL 是否可达
            is_reachable = await is_url_reachable(session, url)

            if is_reachable:
                # 每个url发送原来的请求 + 原来请求附加参数(多个)
                url = replace_query_values(url, payload)
                tasks.append(fetch(session, url, payload_verifier, reflected_url, proxy=await get_proxy(proxy_pool)))

                for param_joined in generate_params(payload, each_req_param_num, params):
                    url_handled = handle_parameters(url, param_joined)
                    tasks.append(fetch(session, url_handled, payload_verifier, reflected_url, proxy=await get_proxy(proxy_pool)))
            else:
                unreachable += 1

        # 使用 asyncio.gather 收集所有任务的结果
        # 有结果的分为True和False, 没有结果的就是died的
        return (await asyncio.gather(*tasks, return_exceptions=True), unreachable)


# 多进程处理函数
def process_group(args):
    urls, payload, params, each_req_param_num, payload_verifier, bar, proxy_pool = args
    # 使用 asyncio.run 替代创建和关闭事件循环
    results, died = asyncio.run(process_urls(urls, params, each_req_param_num, payload, payload_verifier, proxy_pool))

    success = sum(1 for i in results if i is True)
    fail = len(results) - success
    bar.print_accumulator(1, died, success, fail)


# 主函数
def main():
    urls_file = 'uro.txt'  # url文件
    param_file = "params.txt"  # 参数文件
    payload = "lol123'lol123\"lol123<lol123"  # xss payload # 其中lol123只是简单的回显 # 后三个则分别验证对应字符'"<是否过滤或者编码
    payload_verifier = ["lol123", "lol123'lol123", "lol123\"lol123", "lol123<lol123"]
    each_req_param_num = 30  # 对于全部的参数进行分割, 每次请求使用多少参数, 根据目标服务器承受能力决定
    # 50 -> (died:95, success:1967, fail:4459) - 21/url
    # 40 -> (died:95, success:2274, fail:5682) - 26/url
    # 30 -> (died:95, success:4289, fail:6421) - 34/url -- 成功的比例最高
    # 20 -> (died:95, success:5588, fail:10018) - 51/url
    # 10 -> (died:95, success:5699, fail:25207) - 101/url
    batch_size = 100  # 每个批次处理的 URL 数量, 每个批次装进一个进程使用协程处理请求, 需要不断测试
    proxy_pool = True

    with open(urls_file, 'r') as file:
        urls = [line.strip() for line in file]
    print('url 文件读取完毕')
    with open(param_file, 'r') as file:
        params = [line.strip() for line in file]
    print('params 文件读取完毕')


    # 创建进程池
    with Pool(cpu_count()) as pool, Manager() as manager:
        bar = ProcessBar(manager)  # 传入总请求数量
        batches = [(urls[i:i + batch_size], payload, params, each_req_param_num, payload_verifier, bar, proxy_pool) for i in
                   range(0, len(urls), batch_size)]

        bar.set_total(len(batches))

        print( f'cpu数量: {str(cpu_count())}, 共处理批次{len(batches)}, 每批{batch_size}个url, 每个url至少发送{len(params) // each_req_param_num + 1}次请求')
        # 处理每个批次
        for batch in batches:
            pool.map(process_group, [batch])
        print()


if __name__ == "__main__":
    print("""
    安装
    pip3 install aiohttp

    [Reflect Xss 全参数检测]
    特色: 使用多进程+协程执行 (实际上cpu使用率100%, 没有go的多核能力cpu达到400%等, 但因使用协程也很快)

    1. 从uro.txt读取URLs
    2. 从params.txt读取参数名称
    3. url会先测活, 比如超时或者任何无法访问情况则不会发送后续payload. 同时success和fail计数是根存活url来计数的, 失败的是添加参数后服务端无响应的情况
    4. 使用xss的payload`lol123'lol123"lol123<lol123`插入每个参数的value处，并且每30个参数后发一次请求包 (原url会替换参数value后请求一次, 然后参数附加在后面继续请求, 并且考虑到有参数/无参数的url)
    5. 对于全部请求，仅检查响应中是否存在字符串`lol123|lol123<lol123|lol123'lol123|lol123"lol123`有则打印
    """)
    main()
