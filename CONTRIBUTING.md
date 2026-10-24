# 参与开发

欢迎补充招聘渠道、简历格式支持、匹配解释和无障碍体验。

1. 使用 Python 3.10+ 创建虚拟环境，安装 `requirements.txt`。
2. 使用合成简历和独立 `--data` 目录开发。不得在测试、截图、日志和提交中包含真实求职者资料。
3. 运行 `python -m unittest discover -s tests -v` 和 `node --check static/app.js`。
4. 浏览器执行测试另需 `requirements-executor.txt` 和 Chromium。未安装时应明确跳过，不把跳过算通过。
5. 新渠道须有来源、稳定岗位 ID、采集时间、分页预算、零结果与受阻区分、去重和结构变动测试。说明哪些行为只在夹具通过、哪些真正访问过公开站点。
6. 不接收绕过验证码、隐蔽获取 Cookie、未经确认发送消息或自动提高申请额度的变更。

本项目采用 MIT 许可证。请勿复制许可证不兼容的实现；引用公开接口文档与设计机制时在 `THIRD_PARTY_NOTICES.md` 或调研文档标注来源。

直接在本仓库开发并提交 PR。提交前运行 `python scripts/build_release.py --check`，检查所有已跟踪文件中是否有私人目录、个人绝对路径或类似密钥的内容；CI 会执行同一检查。不带参数运行时，用已跟踪文件制作可复核的源码包。
