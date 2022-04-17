#!/usr/bin/env python3
# ========================================================================================
# Sanata Search
#
# Retrieve ES data based on tool (nmap,httpx,nuclei, etc..)
# See: conf/santacruz.yml
# View README.md for additional information
#
# [/csh:]> date "+%D"
# 04/17/22
# ========================================================================================
import os
import sys
import json
import time
import argparse
import requests
import base64
import hashlib
import uuid
import yaml
from urllib.parse import urlparse

# nuclei
def nuclei_bldq(es_host,ip_addr,stime,etime,slimit):
    _dict = {}
    _dict['_uri'] = es_host + '/nuclei/_search?filter_path=hits.hits._source'

    _dict['_search'] = {
              "query": {
                   "bool": {
                      "must": [],
                      "filter": [{"range": {"@timestamp": {"gte": stime, "lte": etime}}}]
                   }
              },
              "_source": {
                  "includes": ["@timestamp", "event.ip", "event.info.severity",
                                 "event.info.name", "event.matched-at", "event.template-id",
                                 "event.info.classification.cvss-score", "event.info.description"]
             },
             "size": slimit
      }

    if ip_addr:
       match_ip = {"match": {"event.ip": ip_addr}}
       _dict['_search']['query']['bool']['must'].append(match_ip)

    return _dict

# nmap
def nmap_bldq(es_host,ip_addr,stime,etime,slimit):
    _dict = {}
    _dict['_uri'] = es_host + '/nmap/_search?filter_path=hits.hits._source'

    _dict['_search'] = {
              "query": {
                   "bool": {
                      "must": [],
                      "filter": [{"range": {"time": {"gte": stime, "lte": etime}}}]
                   }
              },
              "_source": {
                  "includes": ["time","ip","port","protocol","script","script_output"]
             },
             "size": slimit
      }

    if ip_addr:
       match_ip = {"match": {"ip": ip_addr}}
       _dict['_search']['query']['bool']['must'].append(match_ip)

    return _dict

# httpx is called from nmap nse (httpx.nse)
# aggregation note:
# "aggs": {
#    "script_output": {
#      "terms": {
#        "field": "script_output.keyword"
#      }
#    }
#  },
def httpx_bldq(es_host,ip_addr,stime,etime,slimit):
    _dict = {}
    _dict['_uri'] = es_host + '/nmap/_search?filter_path=hits.hits._source'

    _dict['_search'] = {
              "query": {
                   "bool": {
                      "must": [{"match": {"script": "httpx"}}],
                      "filter": [
                          {"exists": {"field": "script_output"}},
                          {"range": {"time": {"gte": stime, "lte": etime}}}
                      ]
                   }
              },
              "_source": {
                  "includes": ["time","script","script_output"]
             },
             "size": slimit
      }

    if ip_addr:
       match_ip = {"match": {"ip": ip_addr}}
       _dict['_search']['query']['bool']['must'].append(match_ip)

    return _dict

def get_indexes(es_session,es_host,verbose):
    index_URI = es_host + '/_cat/indices?h=index&format=json'
    index_arr = []

    r = es_session.get(index_URI, verify=False)
    if r.status_code != 200:
       print(f"[ERROR]: Connection failed, got {r.status_code} response!")
       return sys.exit(-1)

    idx_json = json.loads(r.text)
    for idx in idx_json:
        if not idx['index'].startswith('.'):
           index_arr.append(idx['index'])

    return index_arr

def init_ESsession(user,passwd,api_URL,verbose):
    if verbose:
       print(f"[INFO]: Connecting to Elasticsearch: {api_URL}")

    session = requests.Session()
    ctype_header = {"Content-Type": "application/json"}
    session.headers.update(ctype_header)

    if user:
        userpass = user + ':' + passwd
        encoded_u = base64.b64encode(userpass.encode()).decode()
        auth_header = {"Authorization" : "Basic %s" % encoded_u}
        session.headers.update(auth_header)

    # ES connection
    r = session.get(api_URL, headers=session.headers, verify=False)
    if r.status_code != 200:
       print(f"[ERROR]: Connection failed, got {r.status_code} response!")
       return sys.exit(-1)

    return session

def init_sc(args):
    opts = {}
    opts['verbose'] = args.verbose

    conf = yaml.safe_load(args.config)
    if conf['elasticsearch']['ssl']:
       opts['es_host'] = 'https://' + conf['elasticsearch']['ip']
    else:
       opts['es_host'] = 'http://' + conf['elasticsearch']['ip']

    opts['es_host'] += ':' + str(conf['elasticsearch']['port'])
    opts['es_user']  = conf['elasticsearch']['username']
    opts['es_pass']  = conf['elasticsearch']['password']

    # ES Session
    opts['es_session'] = init_ESsession(opts['es_user'],opts['es_pass'],opts['es_host'],opts['verbose'])

    if args.tool != 'all':
       if args.tool not in conf['tool_list']:
          print(f"[ERROR]: Unknown tool: \"{args.tool}\", check {args.config.name}")
          return sys.exit(-1)

    # Index uri based on configured tools
    opts['tool']      = args.tool
    opts['tool_list'] = conf['tool_list']

    for tool in opts['tool_list']:
        if tool == 'nmap':
           opts['nmap'] = nmap_bldq(opts['es_host'],args.addr,args.start,args.end,args.limit)

        elif tool == 'httpx':
           opts['httpx'] = httpx_bldq(opts['es_host'],args.addr,args.start,args.end,args.limit)

        elif tool == 'nuclei':
           opts['nuclei'] = nuclei_bldq(opts['es_host'],args.addr,args.start,args.end,args.limit)

    opts['oformat'] = args.output

    return opts

def main():
    parser = argparse.ArgumentParser(description='-: Santa Search :-', epilog="View README.md for extented help.\n", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-c', '--config', help='Path to santacruz.yml configuration file', dest='config', metavar='[file]', type=argparse.FileType('r'), required=True)
    parser.add_argument('-a', '--addr',  help='Search for IP address', dest='addr', metavar='[ip address]', action='store')
    parser.add_argument('-s', '--start', help='Search from start time (default: now-24h)', default="now-24h", dest='start', metavar='[date]', action='store')
    parser.add_argument('-e', '--end',   help='Search to end time (default: now)', default="now", dest='end', metavar='[date]', action='store')
    parser.add_argument('-l', '--limit', help='Limit number of results (default: 100)', default=100, dest='limit', metavar='[limit]', action='store', type=int)
    parser.add_argument('-o', '--output', help='Output format (default: txt)', default="txt", dest='output', metavar='[format]', action='store')
    parser.add_argument('-t', '--tool', help='Search for data based on tool name (default: all)', default="all", dest='tool', metavar='[name]', action='store')
    parser.add_argument('-v', '--verbose', help='Verbose output', action="store_true")

    opt_args = parser.parse_args()
    sc_session = init_sc(opt_args)

    print(sc_session)

if __name__ == "__main__":
        main()

