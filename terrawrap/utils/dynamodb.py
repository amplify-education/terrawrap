"""Module for interacting with DynamoDB"""
from typing import Any, Dict

import boto3
from amplify_aws_utils.resource_helper import throttled_call


class DynamoDB:
    """Class for operating with DynamoDB"""

    def __init__(self, region: str, client=None):
        self.client = client or boto3.client('dynamodb', region_name=region)

    def upsert_item(
            self,
            table_name: str,
            primary_key_name: str,
            primary_key_value: str,
            attribute_name: str,
            attribute_value: str
    ) -> Dict[str, Any]:
        """
        Insert/update items in a DynamoDB table for a specific primary key value.
        The value inserted/updated is of type string.
        :param table_name: DynamoDB table name
        :param primary_key_name: Table's primary key name
        :param primary_key_value: Table's primary key value
        :param attribute_name: Item attribute to be inserted/updated
        :param attribute_value: Attribute value to be inserted/updated
        :return: response
        """
        key = {primary_key_name: {'S': primary_key_value}}
        expression_attribute_values = {':d': {'S': attribute_value}}
        update_expression = 'SET {} = :d'.format(attribute_name)

        return throttled_call(
            self.client.update_item,
            TableName=table_name,
            Key=key,
            ExpressionAttributeValues=expression_attribute_values,
            UpdateExpression=update_expression
        )

    def delete_item(
            self,
            table_name: str,
            primary_key_name: str,
            primary_key_value: str,
    ):
        """
        Convenience function for deleting an item from a DynamoDB table with a specific primary key value.
        :param table_name: DynamoDB table name
        :param primary_key_name: Table's primary key name
        :param primary_key_value: Table's primary key value
        :return: response
        """
        key = {primary_key_name: {'S': primary_key_value}}

        return throttled_call(
            self.client.delete_item,
            TableName=table_name,
            Key=key,
        )
