module "module_instance_1" {
  source = "../../../../../modules/aws/docker_application/v4"
  foo = "bar"
}

module "module_instance_2" {
  source = "./modules/custom_pipeline_module"
  foo = "bar"
}
