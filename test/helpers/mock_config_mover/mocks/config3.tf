module "module_instance_1" {
  source = "../../../modules/aws/s3_bucket/v3"
  foo = "bar"
}

bar = "foo"

module "module_instance_2" {
  source = "../modules/custom_website_module"
  foo = "bar"
}
