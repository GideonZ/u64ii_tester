import boto3 as aws
import botocore
import os

class Database:
    def __init__(self):
        with open(os.path.expanduser("~/.config/aws_credentials"), "r") as cred:
            lines = [line for line in cred]
            self.ACCESS_KEY = lines[0].strip()
            self.SECRET_KEY = lines[1].strip()
        self.open_tables()

    def open_tables(self):
        dynamodb = aws.resource('dynamodb', region_name = 'us-east-1', aws_access_key_id = self.ACCESS_KEY, aws_secret_access_key = self.SECRET_KEY)
        self.test = dynamodb.Table('test')
        self.u64ii_boards = dynamodb.Table('u64ii_boards')
        self.u64ii_tests = dynamodb.Table('u64ii_tests')
        self.u64ii_logs = dynamodb.Table('u64ii_logs')

    def dump_sandbox(self):
        for item in self.test.scan()['Items']:
            print(item)

    def dump_boards(self):
        for item in self.u64ii_boards.scan()['Items']:
            print(item)

    def dump_tests(self):
        for item in self.u64ii_tests.scan()['Items']:
            print(item)

    def get_board(self, serial):
        response = self.u64ii_boards.get_item(Key = { 'serial' : serial })
        if 'Item' in response:
            return response['Item']

    def add_board(self, dct):
        try:
            response = self.u64ii_boards.put_item(Item = dct)
        except botocore.errorfactory.ResourceNotFoundException as e:
            print(e)

    def add_test_results(self, dct):
        try:
            response = self.u64ii_tests.put_item(Item = dct)
        except botocore.errorfactory.ResourceNotFoundException as e:
            print(e)

    def add_log(self, dct):
        try:
            response = self.u64ii_logs.put_item(Item = dct)
        except botocore.errorfactory.ResourceNotFoundException as e:
            print(e)

if __name__ == '__main__':
    db = Database()
    print("BOARDS:")
    db.dump_boards()
    print("SANDBOX:")
    db.dump_sandbox()

    print(db.get_board("proto_s3"))
    print(db.test.get_item(Key = { 'serial' : '0002' } ))
    print(db.test.put_item(Item = { 'serial' : '0011', 'bogus' : 1 }))
