# Copyright (c) SWAN Development Team.
# Author: Omar.Zapata@cern.ch 2021
import json
import os
import shutil
import subprocess

import tornado
from notebook.base.handlers import APIHandler
from notebook.utils import url_path_join
from tornado.web import StaticFileHandler
from traitlets import Bool, Unicode
from traitlets.config import Configurable

from .utils import (get_project_info, get_project_path, get_project_readme,
                    get_user_script_content)


class SwanProjects(Configurable):
    stacks_path = Unicode(
        os.path.dirname(os.path.abspath(__file__))+'/stacks.json',
        config=True,
        help="The path to the JSON containing stack configuration")

class ProjectInfoHandler(APIHandler):
    @tornado.web.authenticated
    def post(self):
        """
        Post request for the SwanLauncher/SwanFileBrowser,
        this endpoint returns project information such as stack, release, platform etc..
        if the path is not inside the project return and empty project data.

        At th same time this endpoint allows to set the kernel spec manager path,
        to load and unload the kernels according to the project information.
        """
        input_data = self.get_json_body()
        path = input_data["path"]
        project = get_project_path(path)
        self.kernel_spec_manager.set_path(path)
        project_data = {}
        if project is not None:
            project_data = get_project_info(project)

            project_data["name"] = project.split(os.path.sep)[-1]
            readme = get_project_readme(project)
            if readme is not None:
                project_data["readme"] = readme
            project_data["user_script"] = get_user_script_content(project)
        payload = {"project_data": project_data}
        self.finish(json.dumps(payload))


class StacksInfoHandler(APIHandler):

    swan_projects_config = None

    def initialize(self):
        self.swan_projects_config = SwanProjects(config=self.config)

    @tornado.web.authenticated
    def get(self):
        """
        This endpoint is required for the project dialog, it's returning the information save on stacks.json
        """
        with open(self.swan_projects_config.stacks_path) as f:
            stacks = json.loads(f.read())
        self.finish(json.dumps({"stacks": stacks}))


class KernelSpecManagerPathHandler(APIHandler):
    @tornado.web.authenticated
    def post(self):
        """
        This endpoint is required for the project kernel spec manager, it's it is setting the path to
        check if we are inside a project to change the kernel spec manager path
        """
        input_data = self.get_json_body()
        path = input_data["path"]
        self.log.info(f"KernelSpecManagerPathHandler = {input_data}")
        self.kernel_spec_manager.set_path(path)
        project = get_project_path(path)
        self.finish(json.dumps(
            {"is_project": project is not None, 'path': path}))


class CreateProjectHandler(APIHandler):
    @tornado.web.authenticated
    def post(self):
        """
        Endpoint to create a project, receive project information such as name, stack, platform, release, user_script.
        The project is created at $HOME/SWAN_projects/project_name and a hidden json ".swanproject" file with the information
        project is set inside the project folder.
        """
        input_data = self.get_json_body()
        self.log.info(f"creating project {input_data}")

        name = input_data["name"]
        stack = input_data["stack"]  # CMSSW/LCG
        platform = input_data["platform"]  # SCRAM
        release = input_data["release"]  # CMSSW
        user_script = input_data["user_script"]

        project_dir = os.environ["HOME"] + "/SWAN_projects/" + name
        os.makedirs(project_dir)
        swan_project_file = project_dir + os.path.sep + '.swanproject'
        swan_project_content = {'stack': stack, 'release': release,
                                'platform': platform}

        with open(swan_project_file, 'w+') as f:
            f.write(json.dumps(swan_project_content, indent=4, sort_keys=True))
            f.close()

        swan_user_script_file = project_dir + os.path.sep + '.userscript'
        with open(swan_user_script_file, 'w') as f:
            f.write(user_script)
            f.close()

        command = ["env","-i","HOME=%s"%os.environ["HOME"]]
        #checking if we are on EOS to add the env variables
        #we required this to read/write in a isolate environment with EOS
        if "OAUTH2_FILE" in os.environ:
            command.append("OAUTH2_FILE=%s"%os.environ["OAUTH2_FILE"])
        if "OAUTH2_TOKEN" in os.environ:
            command.append("OAUTH2_TOKEN=%s"%os.environ["OAUTH2_TOKEN"])
        if "OAUTH_INSPECTION_ENDPOINT" in os.environ:
            command.append("OAUTH_INSPECTION_ENDPOINT=%s"%os.environ["OAUTH_INSPECTION_ENDPOINT"])
        command += ["/bin/bash","-c", "swan_kmspecs --project_name %s"%name]
        #print(" ".join(command))
        proc = subprocess.Popen(command, stdout=subprocess.PIPE)
        proc.wait()
        output = proc.stdout.read().decode("utf-8")
        self.log.info(f"swan_kmspecs output: {output}")
        proc.communicate()

        data = {"project_dir": "SWAN_projects/" + name,
                "msg": "created project: %s"%name}
        self.finish(json.dumps(data))


class EditProjectHandler(APIHandler):

    @tornado.web.authenticated
    def post(self):
        """
        This endpoint allows to edit project information, such as name, stack, platform etc..
        The project can be renamed from $HOME/SWAN_projects/old_name to $HOME/SWAN_projects/name
        and metadata in the .swanproject is updated.
        """
        input_data = self.get_json_body()
        print("Called Editing project")
        print(input_data)
        old_name = input_data["old_name"]
        name = input_data["name"]
        stack = input_data["stack"]  # CMSSW/LCG
        platform = input_data["platform"]  # SCRAM
        release = input_data["release"]  # CMSSW
        user_script = input_data["user_script"]

        project_dir = os.environ["HOME"] + "/SWAN_projects/" + name
        if old_name != name:
            old_project_dir = os.environ["HOME"] + "/SWAN_projects/" + old_name
            os.rename(old_project_dir, project_dir)

        swan_project_file = project_dir + os.path.sep + '.swanproject'
        swan_project_content = {'stack': stack, 'release': release,
                                'platform': platform}
        kernel_dir = project_dir + "/.local/share/jupyter/kernels"

        # removing old native kernels for python only(this is generated by us)
        if os.path.exists(kernel_dir + "/python2"):
            shutil.rmtree(kernel_dir + "/python2")

        if os.path.exists(kernel_dir + "/python3"):
            shutil.rmtree(kernel_dir + "/python3")

        with open(swan_project_file, 'w+') as f:
            f.write(json.dumps(swan_project_content, indent=4, sort_keys=True))
            f.close()

        swan_user_script_file = project_dir + os.path.sep + '.userscript'
        with open(swan_user_script_file, 'w') as f:
            f.write(user_script)
            f.close()

        command = ["swan_kmspecs", "--project_name", name]
        self.log.info(f"running {command} ")
        proc = subprocess.Popen(command, stdout=subprocess.PIPE)
        proc.wait()
        output = proc.stdout.read().decode("utf-8")
        self.log.info(f"result {output} ")
        proc.communicate()

        data = {"project_dir": "SWAN_projects/" + name,
                "msg": "edited project: {}".format(name)}
        self.finish(json.dumps(data))


# URL to handler mappings
def setup_handlers(web_app, url_path):
    host_pattern = ".*$"
    base_url = web_app.settings["base_url"]

    # Prepend the base_url so that it works in a jupyterhub setting
    create_pattern = url_path_join(base_url, url_path, "project/create")
    edit_pattern = url_path_join(base_url, url_path, "project/edit")
    project_pattern = url_path_join(base_url, url_path, "project/info")
    stack_pattern = url_path_join(base_url, url_path, "stacks/info")
    ksm_path_pattern = url_path_join(base_url, url_path, "kernelspec/set")
    handlers = [(create_pattern, CreateProjectHandler)]
    handlers.append((edit_pattern, EditProjectHandler))
    handlers.append((project_pattern, ProjectInfoHandler))
    handlers.append((stack_pattern, StacksInfoHandler))
    handlers.append((ksm_path_pattern, KernelSpecManagerPathHandler))

    web_app.add_handlers(host_pattern, handlers)

    # Prepend the base_url so that it works in a jupyterhub setting
    doc_url = url_path_join(base_url, url_path, "static")
    doc_dir = os.getenv(
        "SWAN_JLAB_SERVER_STATIC_DIR",
        os.path.join(os.path.dirname(__file__), "static"),
    )
    handlers = [("{}/(.*)".format(doc_url),
                 StaticFileHandler, {"path": doc_dir})]
    web_app.add_handlers(".*$", handlers)
