import unittest
from urllib.parse import parse_qs, urlsplit

from hunt.minimax import HOST, detail, listing, official_board, read_jobs, read_request, search_url
from hunt.sources import SourceError


BOARD = 'https://' + HOST + '/index/'
CAREER = 'https://www.minimaxi.com/careers'
ID = '7641148041870117126'
URL = BOARD + 'position/' + ID + '/detail'
CAREER_HTML = ('<a href="https://' + HOST + '/379481/?project=7496820276634634537">Top Talent 人才计划</a>'
               '<a href="' + BOARD + '">社会招聘 查看所有职位</a>')


def detail_html(title='Agent Engineer', recruitment='社招', requirements=True):
    return ('<div class="jobDetail"><div class="job-header"><span data-test="jobTitle">' + title + '</span></div>'
            '<div class="job-info"><span>上海、北京</span><span>' + recruitment + '</span><span>全职</span></div>'
            '<div class="block-title">职位描述</div><div class="block-content">'
            'Build reliable AI Agent services with Python. Own tool execution, observability and data workflows.</div>'
            + ('<div class="block-title">职位要求</div><div class="block-content">'
               'Experience building distributed applications and operating production APIs.</div>' if requirements else '')
            + '<div class="apply-block"><button>投递</button></div></div>')


def list_html(title='Agent Engineer', recruitment='社招', ident=ID, path=None):
    path = path or '/index/position/' + ident + '/detail'
    return ('<div>开启新的工作（21）</div><a data-id="' + ident + '" href="' + path + '">'
            '<div data-test="positionItem">' + title + '</div><div class="positionItem-subTitle">上海 ' + recruitment + ' 全职</div>'
            '<div class="positionItem-jobDesc">Build AI Agent services</div></a>')


class MiniMaxTests(unittest.TestCase):
    def test_selects_official_social_entry_not_talent_or_campus(self):
        self.assertEqual(official_board(CAREER_HTML, CAREER), BOARD)
        for html in ['<a href="' + BOARD + '">MiniMax校招</a>',
                     '<a href="https://' + HOST + '/379481/">社会招聘</a>',
                     '<a href="https://untrusted.example/index/">社会招聘</a>']:
            with self.assertRaises(SourceError):
                official_board(html, CAREER)

    def test_search_preserves_observed_query_contract_and_escapes_terms(self):
        parsed = urlsplit(search_url(BOARD, 'AI / Agent & developer'))
        self.assertEqual(parsed.hostname, HOST)
        self.assertEqual(parse_qs(parsed.query)['keywords'], ['AI / Agent & developer'])
        self.assertEqual(parse_qs(parsed.query)['limit'], ['10'])
        self.assertNotIn('project', parse_qs(parsed.query))

    def test_list_requires_same_tenant_social_identity(self):
        rows, count = listing(list_html(), BOARD)
        self.assertEqual(rows[0]['url'], URL)
        self.assertEqual(count, 21)
        with self.assertRaises(SourceError):
            listing(list_html(recruitment='校招'), BOARD)
        with self.assertRaises(SourceError):
            listing(list_html(path='https://untrusted.example/index/position/' + ID + '/detail'), BOARD)
        with self.assertRaises(SourceError):
            listing(list_html(path='/index/position/9999999999999999999/detail'), BOARD)

    def test_empty_rendered_count_is_not_proof_of_no_vacancies(self):
        with self.assertRaises(SourceError) as error:
            listing('<div>开启新的工作（0） 暂无职位，请尝试其他搜索条件</div>', BOARD)
        self.assertEqual(error.exception.status, 'blocked')

    def test_full_detail_keeps_identity_location_and_requirements(self):
        job = detail(detail_html(), URL, 'Agent Engineer')
        self.assertEqual(job['platform_id'], 'minimax:' + ID)
        self.assertEqual(job['location'], '上海、北京')
        self.assertIn('distributed applications', job['requirements_text'])
        self.assertEqual(job['raw']['employment_type'], '全职')
        self.assertEqual(job['application_url'], URL)
        self.assertTrue(job['raw']['requires_public_browser'])

    def test_partial_wrong_job_and_campus_details_are_rejected(self):
        for html in [detail_html(requirements=False), detail_html('Different Engineer'), detail_html(recruitment='校招'),
                     detail_html().replace('<button>', '<button disabled>')]:
            with self.assertRaises(SourceError):
                detail(html, URL, 'Agent Engineer')

    def test_only_exact_public_search_post_is_allowed(self):
        self.assertTrue(read_request('POST', 'https://' + HOST + '/api/v1/search/job/posts?keyword=Agent'))
        for url in ['https://' + HOST + '/api/v1/apply',
                    'https://' + HOST + '/api/v1/search/job/posts/submit',
                    'https://other.jobs.feishu.cn/api/v1/search/job/posts',
                    'https://user:pass@' + HOST + '/api/v1/search/job/posts',
                    'http://' + HOST + '/api/v1/search/job/posts']:
            self.assertFalse(read_request('POST', url))
        self.assertFalse(read_request('DELETE', 'https://' + HOST + '/api/v1/search/job/posts'))

    def test_bounded_reads_produce_provenance_without_an_application_request(self):
        class Renderer:
            def __init__(self): self.urls = []
            def read(self, url):
                self.urls.append(url)
                body = detail_html() if '/position/' in url else list_html()
                return dict(body=body.encode(), status=200, url=url)
        renderer = Renderer(); report = dict(pages=1, fetched=0)
        def no_http(*args, **kwargs): self.fail('The official HTML is already supplied')
        jobs = list(read_jobs(dict(url=CAREER), no_http, ['Agent'], 2, 2, report, renderer, CAREER_HTML))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(len(renderer.urls), 2)
        self.assertTrue(all('/resume/' not in url and '/apply' not in url for url in renderer.urls))
        self.assertEqual(jobs[0]['raw']['application_route']['observed_url'], BOARD)
        self.assertTrue(report['truncated'])

    def test_plain_http_mode_requests_renderer_instead_of_claiming_broken_entry(self):
        report = dict(pages=1, fetched=0)
        with self.assertRaises(SourceError) as error:
            list(read_jobs(dict(url=CAREER), None, ['Agent'], 2, 2, report, html=CAREER_HTML))
        self.assertEqual(error.exception.status, 'needs_browser')

    def test_redirect_to_other_job_is_not_accepted(self):
        class Renderer:
            def read(self, url):
                body = detail_html() if '/position/' in url else list_html()
                return dict(body=body.encode(), status=200, url=url.replace(ID, '9999999999999999999'))
        report = dict(pages=1, fetched=0)
        with self.assertRaises(SourceError):
            list(read_jobs(dict(url=CAREER), None, ['Agent'], 2, 2, report, Renderer(), CAREER_HTML))
        self.assertEqual(report['detail_errors'][0]['status'], 'identity_mismatch')


if __name__ == '__main__':
    unittest.main()
