import unittest

import indexnow


class IndexNowTest(unittest.TestCase):
    def test_urls_and_batches(self):
        sitemap = "<urlset><url><loc>https://eunodia.com/</loc></url><url><loc>https://eunodia.com/a?x=1&amp;y=2</loc></url></urlset>"
        self.assertEqual(indexnow.urls_of(sitemap), ["https://eunodia.com/", "https://eunodia.com/a?x=1&y=2"])
        sent = indexnow.payloads([str(i) for i in range(indexnow.BATCH + 1)], "https://eunodia.com/", "abc")
        self.assertEqual([len(p["urlList"]) for p in sent], [indexnow.BATCH, 1])
        self.assertEqual(sent[0]["host"], "eunodia.com")
        self.assertEqual(sent[0]["keyLocation"], "https://eunodia.com/abc.txt")


if __name__ == "__main__":
    unittest.main()
