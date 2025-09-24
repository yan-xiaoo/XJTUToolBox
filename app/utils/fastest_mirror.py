# 检查存储库及其镜像中，哪个 API 的速度最快
# 原始代码来自：https://github.com/moesnow/March7thAssistant/blob/main/tasks/base/fastest_mirror.py


import time
import traceback

import requests
import concurrent.futures


class FastestMirror:
    # @staticmethod
    # def get_github_mirror(download_url):
    #     # mirror_urls = [
    #     #     download_url,
    #     #     f"https://github.kotori.top/{download_url}",
    #     # ]
    #     # return FastestMirror.find_fastest_mirror(mirror_urls, 5)
    #     return f"https://github.kotori.top/{download_url}"

    @staticmethod
    def get_github_api_mirror(user, repo, latest=True):
        if latest:
            mirror_urls = [
                f"https://api.github.com/repos/{user}/{repo}/releases/latest",
                f"https://gh-api.xjtutoolbox.com/https://api.github.com/repos/{user}/{repo}/releases/latest",
            ]
            return FastestMirror.find_fastest_mirror(mirror_urls, 15)
        else:
            mirror_urls = [
                f"https://api.github.com/repos/{user}/{repo}/releases",
                f"https://gh-api.xjtutoolbox.com/https://api.github.com/repos/{user}/{repo}/releases",
            ]
            return FastestMirror.find_fastest_mirror(mirror_urls, 15)

    @staticmethod
    def get_download_mirror(download_urls):
        """
        比较多个下载 URL，以便确定最快的一个
        """
        return FastestMirror.find_fastest_mirror(download_urls, 15)

    @staticmethod
    def find_fastest_mirror(mirror_urls, timeout=5):
        """测速并找到最快的镜像。"""
        def check_mirror(mirror_url):
            try:
                start_time = time.time()
                response = requests.head(mirror_url, timeout=timeout, allow_redirects=True)
                end_time = time.time()
                if response.status_code == 200:
                    return mirror_url, end_time - start_time
            except Exception:
                traceback.print_exc()
                pass
            return None, None

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [executor.submit(check_mirror, url) for url in mirror_urls]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
            valid_results = [(url, t) for url, t in results if t is not None]

            if valid_results:
                fastest_mirror, _ = min(valid_results, key=lambda x: x[1])
            else:
                fastest_mirror = None

        return fastest_mirror if fastest_mirror else mirror_urls[0]