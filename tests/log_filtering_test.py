#!/usr/bin/env python3
import os
import eth_utils

from conflux.config import default_config
from conflux.filter import Filter
from conflux.rpc import RpcClient
from conflux.utils import sha3 as keccak, priv_to_addr
from test_framework.blocktools import create_transaction, encode_hex_0x
from test_framework.test_framework import ConfluxTestFramework
from test_framework.util import *
from test_framework.mininode import *

CONTRACT_PATH = "contracts/EventsTestContract_bytecode.dat"
CONSTRUCTED_TOPIC = encode_hex_0x(keccak(b"Constructed(address,address)"))
CALLED_TOPIC = encode_hex_0x(keccak(b"Called(address,uint32)"))
NUM_CALLS = 20

class LogFilteringTest(ConfluxTestFramework):
    def set_test_params(self):
        self.num_nodes = 1

    def setup_network(self):
        self.setup_nodes()

    def run_test(self):
        priv_key = default_config["GENESIS_PRI_KEY"]
        sender = eth_utils.encode_hex(priv_to_addr(priv_key))

        self.rpc = RpcClient(self.nodes[0])

        # apply filter, we expect no logs
        filter = Filter()
        result = self.rpc.get_logs(filter)
        assert_equal(result, [])

        # deploy contract
        bytecode_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), CONTRACT_PATH)
        assert(os.path.isfile(bytecode_file))
        bytecode = open(bytecode_file).read()
        _, contractAddr = self.deploy_contract(sender, priv_key, bytecode)

        # apply filter, we expect a single log with 2 topics
        filter = Filter(from_epoch="earliest", to_epoch="latest_state")
        logs0 = self.rpc.get_logs(filter)

        self.assert_response_format_correct(logs0)
        assert_equal(len(logs0), 1)

        assert_equal(len(logs0[0]["topics"]), 2)
        assert_equal(logs0[0]["topics"][0], CONSTRUCTED_TOPIC)
        assert_equal(logs0[0]["topics"][1], self.address_to_topic(sender))
        assert_equal(logs0[0]["data"], self.address_to_topic(sender))

        # call method
        receipt = self.call_contract(sender, priv_key, contractAddr, encode_hex_0x(keccak(b"foo()")), storage_limit=64)

        # apply filter, we expect two logs with 2 and 3 topics respectively
        filter = Filter(from_epoch="earliest", to_epoch="latest_state")
        logs1 = self.rpc.get_logs(filter)

        self.assert_response_format_correct(logs1)
        assert_equal(len(logs1), 2)
        assert_equal(logs1[0], logs0[0])

        assert_equal(len(logs1[1]["topics"]), 3)
        assert_equal(logs1[1]["topics"][0], CALLED_TOPIC)
        assert_equal(logs1[1]["topics"][1], self.address_to_topic(sender))
        assert_equal(logs1[1]["topics"][2], self.number_to_topic(1))

        # apply filter for specific block, we expect a single log with 3 topics
        filter = Filter(block_hashes=[receipt["blockHash"]])
        logs = self.rpc.get_logs(filter)

        self.assert_response_format_correct(logs)
        assert_equal(len(logs), 1)
        assert_equal(logs[0], logs1[1])

        # call many times
        for ii in range(2, NUM_CALLS):
            self.call_contract(sender, priv_key, contractAddr, encode_hex_0x(keccak(b"foo()")), storage_limit=0)

        # apply filter, we expect NUM_CALLS log entries with increasing uint32 fields
        filter = Filter(from_epoch="earliest", to_epoch="latest_state")
        logs = self.rpc.get_logs(filter)

        self.assert_response_format_correct(logs)
        assert_equal(len(logs), NUM_CALLS)

        for ii in range(2, NUM_CALLS):
            assert_equal(len(logs[ii]["topics"]), 3)
            assert_equal(logs[ii]["topics"][0], CALLED_TOPIC)
            assert(logs[ii]["topics"][1] == self.address_to_topic(sender))
            assert_equal(logs[ii]["topics"][2], self.number_to_topic(ii))

        # apply filter for specific topics
        filter = Filter(topics=[CONSTRUCTED_TOPIC])
        logs = self.rpc.get_logs(filter)
        self.assert_response_format_correct(logs)
        assert_equal(len(logs), 1)

        filter = Filter(topics=[CALLED_TOPIC])
        logs = self.rpc.get_logs(filter)
        self.assert_response_format_correct(logs)
        assert_equal(len(logs), NUM_CALLS - 1)

        filter = Filter(topics=[None, self.address_to_topic(sender)])
        logs = self.rpc.get_logs(filter)
        self.assert_response_format_correct(logs)
        assert_equal(len(logs), NUM_CALLS)

        # find logs with `CALLED_TOPIC` as 1st topic and `3` or `4` as 3rd topic
        filter = Filter(topics=[CALLED_TOPIC, None, [self.number_to_topic(3), self.number_to_topic(4)]])
        logs = self.rpc.get_logs(filter)
        self.assert_response_format_correct(logs)
        assert_equal(len(logs), 2)

        # apply filter with limit
        filter = Filter(limit=hex(NUM_CALLS // 2))
        logs = self.rpc.get_logs(filter)

        self.assert_response_format_correct(logs)
        assert_equal(len(logs), NUM_CALLS // 2)

        # apply filter for specific contract address
        _, contractAddr2 = self.deploy_contract(sender, priv_key, bytecode)

        filter = Filter(address=[contractAddr])
        logs = self.rpc.get_logs(filter)
        self.assert_response_format_correct(logs)
        assert_equal(len(logs), NUM_CALLS)

        filter = Filter(address=[contractAddr2])
        logs = self.rpc.get_logs(filter)
        self.assert_response_format_correct(logs)
        assert_equal(len(logs), 1)

        # apply filter to very first epoch, we expect no logs
        filter = Filter(from_epoch="earliest", to_epoch="earliest")
        result = self.rpc.get_logs(filter)
        assert_equal(result, [])

        # generate two blocks with `NUM_CALLS` valid logs in each
        parent_hash = self.rpc.block_by_epoch("latest_mined")['hash']
        start_nonce = self.rpc.get_nonce(sender)

        txs = [self.rpc.new_contract_tx(receiver=contractAddr, data_hex=encode_hex_0x(keccak(b"foo()")), sender=sender, priv_key=priv_key, storage_limit=64, nonce = start_nonce + ii) for ii in range(0, NUM_CALLS)]
        block_hash_1 = self.rpc.generate_custom_block(parent_hash = parent_hash, referee = [], txs = txs)

        txs = [self.rpc.new_contract_tx(receiver=contractAddr, data_hex=encode_hex_0x(keccak(b"foo()")), sender=sender, priv_key=priv_key, storage_limit=64, nonce = start_nonce + NUM_CALLS + ii) for ii in range(0, NUM_CALLS)]
        block_hash_2 = self.rpc.generate_custom_block(parent_hash = block_hash_1, referee = [], txs = txs)

        # blocks not executed yet, filtering should fail
        filter = Filter(block_hashes=[block_hash_1, block_hash_2])
        assert_raises_rpc_error(None, None, self.rpc.get_logs, filter)

        # generate some more blocks to ensure our two blocks are executed
        self.rpc.generate_blocks(10)

        # filtering for these two blocks should return logs in correct order
        filter = Filter(block_hashes=[block_hash_1, block_hash_2])
        logs = self.rpc.get_logs(filter)
        assert_equal(len(logs), 2 * NUM_CALLS)

        for ii in range(0, 2 * NUM_CALLS):
            assert_equal(len(logs[ii]["topics"]), 3)
            assert_equal(logs[ii]["topics"][0], CALLED_TOPIC)
            assert(logs[ii]["topics"][1] == self.address_to_topic(sender))
            assert_equal(logs[ii]["topics"][2], self.number_to_topic(ii + NUM_CALLS))

        # block hash order should not affect log order
        filter = Filter(block_hashes=[block_hash_2, block_hash_1])
        logs2 = self.rpc.get_logs(filter)
        assert_equal(logs, logs2)

        # given a limit, we should receive the _last_ few logs
        filter = Filter(block_hashes=[block_hash_1, block_hash_2], limit = hex(NUM_CALLS + NUM_CALLS // 2))
        logs = self.rpc.get_logs(filter)
        assert_equal(len(logs), NUM_CALLS + NUM_CALLS // 2)

        for ii in range(0, NUM_CALLS + NUM_CALLS // 2):
            assert_equal(len(logs[ii]["topics"]), 3)
            assert_equal(logs[ii]["topics"][0], CALLED_TOPIC)
            assert(logs[ii]["topics"][1] == self.address_to_topic(sender))
            assert_equal(logs[ii]["topics"][2], self.number_to_topic(ii + NUM_CALLS + NUM_CALLS // 2))

        self.log.info("Pass")

    def address_to_topic(self, address):
        return "0x" + address[2:].zfill(64)

    def number_to_topic(self, number):
        return "0x" + ("%x" % number).zfill(64)

    def deploy_contract(self, sender, priv_key, data_hex):
        c0 = self.rpc.get_collateral_for_storage(sender)
        tx = self.rpc.new_contract_tx(receiver="", data_hex=data_hex, sender=sender, priv_key=priv_key, storage_limit=253)
        assert_equal(self.rpc.send_tx(tx, True), tx.hash_hex())
        receipt = self.rpc.get_transaction_receipt(tx.hash_hex())
        assert_equal(receipt["outcomeStatus"], 0)
        address = receipt["contractCreated"]
        c1 = self.rpc.get_collateral_for_storage(sender)
        assert_equal(c1 - c0, 253 * 10 ** 18 // 1024)
        assert_is_hex_string(address)
        return receipt, address

    def call_contract(self, sender, priv_key, contract, data_hex, storage_limit):
        c0 = self.rpc.get_collateral_for_storage(sender)
        tx = self.rpc.new_contract_tx(receiver=contract, data_hex=data_hex, sender=sender, priv_key=priv_key, storage_limit=storage_limit)
        assert_equal(self.rpc.send_tx(tx, True), tx.hash_hex())
        receipt = self.rpc.get_transaction_receipt(tx.hash_hex())
        assert_equal(receipt["outcomeStatus"], 0)
        c1 = self.rpc.get_collateral_for_storage(sender)
        assert_equal(c1 - c0, storage_limit * 10 ** 18 // 1024)
        return receipt

    def assert_response_format_correct(self, response):
        assert_equal(type(response), list)
        for log in response:
            self.assert_log_format_correct(log)

    def assert_log_format_correct(self, log):
        assert_is_hex_string(log["address"])
        assert_is_hex_string(log["epochNumber"])
        assert_is_hex_string(log["logIndex"])
        assert_is_hex_string(log["transactionIndex"])
        assert_is_hex_string(log["transactionLogIndex"])

        assert_is_hash_string(log["blockHash"])
        assert_is_hash_string(log["transactionHash"])

        assert_equal(type(log["topics"]), list)

if __name__ == "__main__":
    LogFilteringTest().main()
