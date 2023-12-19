from functools import wraps

try:
    from neo4j._async.driver import AsyncGraphDatabase as async_db
except ModuleNotFoundError:
    print('Error! You should be running neo4j python driver version 5 to use async features')

from neo4j import GraphDatabase as sync_db
import pandas as pd
import yaml
import datetime
import sys
import gzip
from zipfile import ZipFile
from urllib.parse import urlparse
import boto3
from smart_open import open
import io
import pathlib
import ijson
import io
import bz2
from parse_ttl import TTLParser

import asyncio
import platform
import logging

if platform.system() == 'Windows':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

config = dict()
supported_compression_formats = ['gzip', 'zip', 'bz2', 'none']

class StreamToLogger(object):
    """
    Fake file-like stream object that redirects writes to a logger instance.
    """
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ''

    def write(self, buf):
        temp_linebuf = self.linebuf + buf
        self.linebuf = ''
        for line in temp_linebuf.splitlines(True):
            # From the io.TextIOWrapper docs:
            #   On output, if newline is None, any '\n' characters written
            #   are translated to the system default line separator.
            # By default sys.stdout.write() expects '\n' newlines and then
            # translates them so this is still cross platform.
            if line[-1] == '\n':
                self.logger.log(self.log_level, line.rstrip())
            else:
                self.linebuf += line

    def flush(self):
        if self.linebuf != '':
            self.logger.log(self.log_level, self.linebuf.rstrip())
        self.linebuf = ''

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(message)s',
    handlers=[
        logging.FileHandler("logfile.log"),
        # logging.StreamHandler(sys.stdout)
    ]
)

stdout_logger = logging.getLogger('STDOUT')
sl = StreamToLogger(stdout_logger, logging.INFO)
sys.stdout = sl

stderr_logger = logging.getLogger('STDERR')
sl = StreamToLogger(stderr_logger, logging.ERROR)
sys.stderr = sl

class LocalServer(object):

    def __init__(self):
        self._driver = sync_db.driver(config['server_uri'],
                                      auth=(config['admin_user'],
                                            config['admin_pass']))

        self._async_driver = async_db.driver(config['server_uri'],
                                      auth=(config['admin_user'],
                                            config['admin_pass']))

        self.db_config = {}
        self.database = config['database'] if 'database' in config else None
        if self.database is not None:
            self.db_config['database'] = self.database
        self.basepath = config['basepath'] if 'basepath' in config else None

    def close(self):
        self._driver.close()
        self._async_driver.close()

    async def load_file(self, file):
        # Set up parameters/defaults
        # Check skip_file first so we can exit early
        skip = file.get('skip_file') or False
        mod = 'async' if config['mod'] == 'async' else 'sync' if not config['mod'] or config['mod'] == 'sync' else None
        if mod == 'async' and not config['thread_count']:
            print('Error! thread_count should be specified when running with mod async')
            return

        if skip:
            print("Skipping this file: {}", file['url'])
            return

        print("{} : Reading file", datetime.datetime.utcnow())

        # If file type is specified, use that.  Else check the extension.  Else, treat as csv
        type = file.get('type') or 'NA'
        if type != 'NA':
            if type == 'csv':
                if mod == 'async':
                    print('Error! Async mod is only supported for json files for now')
                    return

                self.load_csv(file)
            elif type == 'json':
                if mod == 'sync':
                    self.load_json(file)
                elif mod == 'async':
                    await self.load_json_async(file)
                else:
                    print('Error! Wrong mod specified. Should be \'sync\' or \'async\'')
            elif type == 'ttl':
                if mod == 'sync':
                    self.load_ttl(file)
                elif mod == 'async':
                    await self.load_ttl_async(file)
                else:
                    print('Error! Wrong mod specified. Should be \'sync\' or \'async\'')
            else:
                print("Error! Can't process file because unknown type", type, "was specified")
        else:
            file_suffixes = pathlib.Path(file['url']).suffixes
            if '.csv' in file_suffixes:
                if mod == 'async':
                    print('Error! Async mod is only supported for json files for now')
                    return

                self.load_csv(file)
            elif '.json' in file_suffixes:
                if mod == 'sync':
                    self.load_json(file)
                elif mod == 'async':
                    await self.load_json_async(file)
                else:
                    print('Error! Wrong mod specified. Should be \'sync\' or \'async\'')
            elif type == 'ttl':
                if mod == 'sync':
                    self.load_ttl(file)
                elif mod == 'async':
                    await self.load_ttl_async(file)
                else:
                    print('Error! Wrong mod specified. Should be \'sync\' or \'async\'')
            else:
                self.load_csv(file)

    # Tells ijson to return decimal number as float.  Otherwise, it wraps them in a Decimal object,
    # which angers the Neo4j driver
    @staticmethod
    def ijson_decimal_as_float(events):
        for prefix, event, value in events:
            if event == 'number':
                value = str(value)
            yield prefix, event, value

    def load_json(self, file):
        with self._driver.session(**self.db_config) as session:
            params = self.get_params(file)
            openfile = file_handle(params['url'], params['compression'])
            # 'item' is a magic word in ijson.  It just means the next-level element of an array
            items = ijson.common.items(self.ijson_decimal_as_float(ijson.parse(openfile)), 'item')
            # Next, pool these into array of 'chunksize'
            halt = False
            rec_num = 0
            chunk_num = 0
            rows = []
            while not halt:
                row = next(items, None)
                if row is None:
                    halt = True
                else:
                    rec_num = rec_num + 1;
                    if rec_num > params['skip_records']:
                        rows.append(row)
                        if len(rows) == params['chunk_size']:
                            print(file['url'], chunk_num, datetime.datetime.utcnow(), flush=True)
                            chunk_num = chunk_num + 1
                            rows_dict = {'rows': rows}
                            session.run(params['cql'], dict=rows_dict).consume()
                            rows = []
                    elif rec_num % 1000 == 0:
                        print('Skipping record %d ' % (rec_num))

            if len(rows) > 0:
                print(file['url'], chunk_num, datetime.datetime.utcnow(), flush=True)
                rows_dict = {'rows': rows}
                session.run(params['cql'], dict=rows_dict).consume()

        print("{} : Completed file", datetime.datetime.utcnow())

    async def load_json_async(self, file):
        try:
            params = self.get_params(file)
            openfile = file_handle(params['url'], params['compression'])
            # 'item' is a magic word in ijson.  It just means the next-level element of an array
            items = ijson.common.items(self.ijson_decimal_as_float(ijson.parse(openfile)), 'item')
            # Next, pool these into array of 'chunksize'
            halt = False
            rec_num = 0
            chunk_num = 0
            rows = []
            process_params = []
            while not halt:
                row = next(items, None)
                if row is None:
                    halt = True
                else:
                    rec_num = rec_num + 1;

                    if rec_num > params['skip_records']:
                        rows.append(row)
                        if len(rows) == params['chunk_size']:
                            chunk_num = chunk_num + 1
                            session_index = (chunk_num - 1) % config['thread_count']
                            rows_dict = {'rows': rows}

                            print(file['url'], 'chunk: ' + str(chunk_num), 'session: ' + str(session_index),
                                  datetime.datetime.utcnow(), flush=True)

                            process_params.append({'session_index': session_index, 'cql': params['cql'],
                                                   'rows_dict': rows_dict})

                            if session_index == config['thread_count'] - 1:
                                tasks = []
                                for p in process_params:
                                    tasks.append(asyncio.create_task(
                                        self.run_cql_wrapper(p['session_index'], p['cql'], p['rows_dict'])))

                                await asyncio.gather(*tasks)

                                process_params = []

                            rows = []
                    elif rec_num % 1000 == 0:
                        print('Skipping record %d ' % (rec_num))

            if len(rows) > 0:
                print(file['url'], chunk_num, datetime.datetime.utcnow(), flush=True)
                rows_dict = {'rows': rows}
                self._driver.session(**self.db_config).run(params['cql'], dict=rows_dict).consume()


            self._driver.session(**self.db_config).close()
            self._async_driver.session(**self.db_config).close()
            self.close()

            print("{} : Completed file", datetime.datetime.utcnow())
        except Exception as e:
            print("Error! " + str(e))
            stderr_logger.exception(e)



    def load_ttl(self, file):
        with self._driver.session(**self.db_config) as session:
            params = self.get_params(file)
            openfile = file_handle(params['url'], params['compression'])
            parser = TTLParser()

            prefixes = parser.read_prefixes(openfile)

            # Next, pool these into array of 'chunksize'
            halt = False
            rec_num = 0
            chunk_num = 0
            rows = []
            while not halt:
                rows = parser.read_data(openfile,prefixes,params['chunk_size'])
                if len(rows) == 0:
                    halt = True
                else:
                    rec_num = rec_num + len(rows)
                    chunk_num = chunk_num + 1
                    if params['skip_chunks'] < chunk_num and params['skip_records'] < rec_num:
                        print(file['url'], chunk_num, datetime.datetime.utcnow(), flush=True)
                        chunk_num = chunk_num + 1
                        rows_dict = {'rows': rows}
                        session.run(params['cql'], dict=rows_dict).consume()
                        rows = []
                    elif rec_num % 1000 == 0:
                        print('Skipping record %d ' % (rec_num))


            if len(rows) > 0:
                print(file['url'], chunk_num, datetime.datetime.utcnow(), flush=True)
                rows_dict = {'rows': rows}
                session.run(params['cql'], dict=rows_dict).consume()

        print("{} : Completed file", datetime.datetime.utcnow())

    async def load_ttl_async(self, file):
        try:
            params = self.get_params(file)
            openfile = file_handle(params['url'], params['compression'])
            parser = TTLParser()

            prefixes = parser.read_prefixes(openfile)

            halt = False
            rec_num = 0
            chunk_num = 0
            rows = []
            process_params = []
            while not halt:
                rows = parser.read_data(openfile, prefixes, params['chunk_size'])
                if len(rows) == 0:
                    halt = True
                else:
                    rec_num = rec_num + len(rows)
                    chunk_num = chunk_num + 1
                    if params['skip_chunks'] < chunk_num and params['skip_records'] < rec_num:
                        session_index = (chunk_num - 1) % config['thread_count']
                        rows_dict = {'rows': rows}

                        print(file['url'], 'chunk: ' + str(chunk_num), 'session: ' + str(session_index),
                              datetime.datetime.utcnow(), flush=True)

                        process_params.append({'session_index': session_index, 'cql': params['cql'],
                                               'rows_dict': rows_dict})

                        if session_index == config['thread_count'] - 1:
                            tasks = []
                            for p in process_params:
                                tasks.append(asyncio.create_task(
                                    self.run_cql_wrapper(p['session_index'], p['cql'], p['rows_dict'])))

                            await asyncio.gather(*tasks)

                            process_params = []

                        rows = []
                    elif rec_num % 1000 == 0:
                        print('Skipping record %d ' % (rec_num))

            if len(rows) > 0:
                print(file['url'], chunk_num, datetime.datetime.utcnow(), flush=True)
                rows_dict = {'rows': rows}
                self._driver.session(**self.db_config).run(params['cql'], dict=rows_dict).consume()

            self._driver.session(**self.db_config).close()
            self._async_driver.session(**self.db_config).close()
            self.close()

            print("{} : Completed file", datetime.datetime.utcnow())
        except Exception as e:
            print("Error! " + str(e))
            stderr_logger.exception(e)


    # This function is created to retry when deadlocks occur
    # However it decreases performance greatly and it seems to be loading the data nevertheless
    # So I set the retry count to 1 so it actually does not take into considerations deadlocks
    async def run_cql_wrapper(self, session_index, cql, dict):
        max_try_count, i, retry = 10, 0, True
        while retry and i < max_try_count:
            try:
                await self.run_cql(session_index, cql, dict)
                retry = False
            except Exception as e:
                if hasattr(e,'code') and e.code == 'Neo.TransientError.Transaction.DeadlockDetected':
                    print('Deadlock detected! Session: %s' % session_index)
                    i += 1
                else:
                    print('Exception occured (Session : %d)' % (session_index))
                    stderr_logger.exception(e)
                    i += 1


    async def run_cql(self, session_index, cql, dict):
        print('Running session %d' % session_index)

        async with self._async_driver.session(**self.db_config) as session:
            await session.run(cql, dict=dict)

        print('Completed session %d' % session_index)

    async def run_cql_tx(self, tx, cql, dict):
        result = await tx.run(cql, dict=dict)
        await tx.commit()

    """fix yelling at me error end"""

    def get_params(self, file):
        params = dict()
        params['skip_records'] = file.get('skip_records') or 0
        params['skip_chunks'] = file.get('skip_chunks') or 0
        config['thread_count'] = config['thread_count'] or 1
        params['compression'] = file.get('compression') or 'none'
        if params['compression'] not in supported_compression_formats:
            print("Unsupported compression format: {}", params['compression'])

        file_url = file['url']
        if self.basepath and file_url.startswith('$BASE'):
            file_url = file_url.replace('$BASE', self.basepath, 1)
        params['url'] = file_url
        print("File {}", params['url'])
        params['cql'] = file['cql']
        params['chunk_size'] = file.get('chunk_size') or 1000
        params['field_sep'] = file.get('field_separator') or ','
        return params

    def load_csv(self, file):
        with self._driver.session(**self.db_config) as session:
            params = self.get_params(file)
            openfile = file_handle(params['url'], params['compression'])

            # - The file interfaces should be consistent in Python but they aren't
            if params['compression'] == 'zip':
                header = openfile.readline().decode('UTF-8')
            else:
                header = str(openfile.readline())

            # Grab the header from the file and pass that to pandas.  This allow the header
            # to be applied even if we are skipping lines of the file
            header = header.strip().split(params['field_sep'])

            # Pandas' read_csv method is highly optimized and fast :-)
            row_chunks = pd.read_csv(openfile, dtype=str, sep=params['field_sep'], error_bad_lines=False,
                                     index_col=False, skiprows=params['skip_records'], names=header,
                                     low_memory=False, engine='c', compression='infer', header=None,
                                     chunksize=params['chunk_size'])

            for i, rows in enumerate(row_chunks):
                print(params['url'], i, datetime.datetime.utcnow(), flush=True)
                # Chunk up the rows to enable additional fastness :-)
                rows_dict = {'rows': rows.fillna(value="").to_dict('records')}
                session.run(params['cql'],
                            dict=rows_dict).consume()

        print("{} : Completed file", datetime.datetime.utcnow())

    def pre_ingest(self):
        if 'pre_ingest' in config:
            statements = config['pre_ingest']

            with self._driver.session(**self.db_config) as session:
                for statement in statements:
                    session.run(statement)

    def post_ingest(self):
        if 'post_ingest' in config:
            statements = config['post_ingest']

            with self._driver.session(**self.db_config) as session:
                for statement in statements:
                    session.run(statement)


def file_handle(url, compression):
    parsed = urlparse(url)
    if parsed.scheme == 's3':
        path = get_s3_client().get_object(Bucket=parsed.netloc, Key=parsed.path[1:])['Body']
    elif parsed.scheme == 'file':
        path = parsed.path
    else:
        path = url
    if compression == 'gzip':
        return gzip.open(path, 'rt', encoding='utf-8')
    elif compression == 'bz2':
        return bz2.open(path, 'rt', encoding='utf-8')
    elif compression == 'zip':
        # Only support single file in ZIP archive for now
        if isinstance(path, str):
            buffer = path
        else:
            buffer = io.BytesIO(path.read())
        zf = ZipFile(buffer)
        filename = zf.infolist()[0].filename
        return zf.open(filename)
    else:
        return open(path)


def get_s3_client():
    return boto3.Session().client('s3')


def load_config(configuration):
    global config
    with open(configuration) as config_file:
        config = yaml.load(config_file, yaml.SafeLoader)

async def main():
    configuration = sys.argv[1]
    load_config(configuration)
    server = LocalServer()
    server.pre_ingest()
    file_list = config['files']
    for file in file_list:
        await server.load_file(file)
    server.post_ingest()
    server.close()


if __name__ == "__main__":
    asyncio.run(main())