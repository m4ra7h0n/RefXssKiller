# RefXssKiller
爬虫url+全参数, 爆破反射xss

## 安装
`pip3 install aiohttp`

## 特色
使用多进程+协程执行 (实际上单核100%, 没有go的多核能力, 但因使用协程也很快)

## 流程
1. 从uro.txt读取URLs
2. 从params.txt读取参数名称
3. 使用xss的payload`lol123'lol123"lol123<lol123`插入每个参数的value处，并且每30个参数后发一次请求包 (原url会替换参数value后请求一次, 然后参数附加在后面继续请求, 并且考虑到有参数/无参数的url)
4. 对于全部请求，仅检查响应中是否存在字符串`lol123|lol123<lol123|lol123'lol123|lol123"lol123`有则打印


运行截图
<img width="1430" alt="image" src="https://github.com/user-attachments/assets/142b3718-aa12-4dda-a8d7-2a32249cae23">

对于大批量数据能力检测
<img width="940" alt="image" src="https://github.com/user-attachments/assets/8cbc879f-0fdd-4cf3-946c-ce4f68675e07">
