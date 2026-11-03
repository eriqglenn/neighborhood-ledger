import socket
import ssl
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
import deed_search as d

class AddressFormatTests(unittest.TestCase):
    def test_postal_fields_do_not_become_street_names(self):
        for address in [
            '1234 Maplewood St 77018',
            '1234 Maplewood Street Houston TX 77018 USA',
            '1234 Maplewood Street Houston Texas 77018-1234 United States',
            '1234 Maplewood St Apt 2 Houston TX 77018',
            '1234 Maplewood Street, Houston, TX 77018',
        ]:
            with self.subTest(address=address):
                number, street, names = d.address_parts(address)
                self.assertEqual((number,street),(1234,'1234 MAPLEWOOD ST'))
                self.assertIn('MAPLEWOOD', names)
                self.assertFalse(any('77018' in n for n in names))

    def test_direction_and_city_named_street_are_preserved(self):
        self.assertEqual(d.address_parts('1200 North Main Street Humble TX 77338')[1], '1200 N MAIN ST')
        self.assertEqual(d.address_parts('123 N Houston 77018')[1], '123 N HOUSTON')
        self.assertEqual(d.address_parts('123 Houston 77018')[1], '123 HOUSTON')

    def test_normalized_query_is_bounded_to_house_and_exact_street(self):
        with patch.object(d,'parcel_query',return_value={'features':[]}) as query:
            d.find_properties('1234 Maplewood St 77018')
        where=query.call_args.args[0]
        self.assertIn('site_str_num = 1234',where)
        self.assertIn("'MAPLEWOOD'",where)
        self.assertNotIn('77018',where)
        self.assertNotIn('LIKE',where)

    def test_connection_failure_is_not_a_missing_address(self):
        cases=[
            (HTTPError(d.PARCEL,403,'Denied',{},None),'HTTP 403'),
            (HTTPError(d.PARCEL,407,'Proxy',{},None),'proxy requires sign-in'),
            (URLError(ssl.SSLCertVerificationError('certificate failed')),'certificate could not be verified'),
            (URLError(socket.gaierror('DNS failed')),'could not resolve'),
            (URLError(TimeoutError()),'timed out'),
        ]
        for error, detail in cases:
            client=Mock();client.open.side_effect=error
            with self.subTest(detail=detail),self.assertRaises(ValueError) as caught:
                d.request(client,d.PARCEL)
            self.assertIn('property-address service',str(caught.exception))
            self.assertIn('www.gis.hctx.net',str(caught.exception))
            self.assertIn(detail,str(caught.exception))
            self.assertIn('not a no-match',str(caught.exception))

    def test_network_html_does_not_become_empty_parcel_result(self):
        with patch.object(d,'request',return_value=b'<html>Network sign in</html>'):
            with self.assertRaisesRegex(ValueError,'not a no-match'):
                d.parcel_query('site_str_num = 1234')

    def test_clerk_failure_identifies_correct_service(self):
        client=Mock();client.open.side_effect=URLError(TimeoutError())
        with self.assertRaisesRegex(ValueError,'County Clerk records service'):
            d.request(client,d.CLERK)
