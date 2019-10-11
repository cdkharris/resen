#!/usr/bin/env python

import docker
import time

# all the docker commands wrapped up nicely

# how do we call docker commands? subprocess? os.call?
# TODO: Use the docker SDK (https://docker-py.readthedocs.io/en/stable/)
class DockerHelper():
    def __init__(self):
        # TODO: define these in a dictionary or json file for each version of resen-core
        # need to get information for each resen-core from somewhere.
        # Info like, what internal port needs to be exposed? Where do we get the image from? etc.
        # mounting directory in the container?
        # What does container.reload() do?  Do we need it?  Where?
        self.container_prefix = 'resen_'

        self.docker = docker.from_env(timeout=300)

    # def create_container(self,**input_kwargs):
    def create_container(self,bucket):
        '''
        Create a docker container with the image, mounts, and ports set in this bucket.  If the image
        does not exist locally, pull it.
        '''

        # set up basic keyword argument dict
        kwargs = dict()
        kwargs['name'] = self.container_prefix + bucket['bucket']['name']
        kwargs['command'] = 'bash'
        kwargs['tty'] = True
        kwargs['ports'] = dict()

        # if bucket has ports, add these to kwargs
        for host, container, tcp in bucket['docker']['port']:
            if tcp:
                key = '%s/tcp' % (container)
            else:
                key = '%s/udp' % (container)
            kwargs['ports'][key] = host

        # if bucket has mounts, add these to kwargs
        kwargs['volumes'] = dict()
        for host, container, permissions in bucket['docker']['storage']:
            temp = {'bind': container, 'mode': permissions}
            kwargs['volumes'][host] = temp

        # check if we have image, if not, pull it
        local_image_ids = [x.id for x in self.docker.images.list()]
        if bucket['docker']['image_id'] not in local_image_ids:
            print("Pulling image: %s" % bucket['docker']['image'])
            print("   This may take some time...")
            status = self.stream_pull_image(bucket['docker']['pull_image'])
            image = self.docker.images.get(bucket['docker']['pull_image'])
            repo,digest = pull_image.split('@')
            # When pulling from repodigest sha256 no tag is assigned. So:
            image.tag(repo, tag=bucket['docker']['image'])
            print("Done!")

        # start the container
        container = self.docker.containers.create(bucket['docker']['image_id'],**kwargs)

        return container.id, container.status


    def remove_container(self,bucket):
        '''
        Remove the container associated with the provided bucket.
        '''
        container = self.docker.containers.get(bucket['docker']['container'])
        container.remove()
        return


    def start_container(self, bucket):
        '''
        Start a container.
        '''
        # need to check if bucket config has changed since last run
        container = self.docker.containers.get(bucket['docker']['container'])
        container.start()   # this does nothing if already started
        container.reload()
        time.sleep(0.1)
        return container.status


    def stop_container(self,bucket):
        '''
        Stop a container.
        '''
        container = self.docker.containers.get(bucket['docker']['container'])
        container.stop()    # this does nothing if already stopped
        container.reload()
        time.sleep(0.1)
        return container.status


    def execute_command(self,bucket,command,user='jovyan',detach=True):
        '''
        Execute a command in a container.  Returns the exit code and output
        '''
        container = self.docker.containers.get(bucket['docker']['container'])
        result = container.exec_run(command,user=user,detach=detach)
        return result.exit_code, result.output


    def stream_pull_image(self,pull_image):
        '''
        Pull image from dockerhub.
        '''
        import datetime
        # time formatting
        def truncate_secs(delta_time, fmt=":%.2d"):
            delta_str = str(delta_time).split(':')
            return ":".join(delta_str[:-1]) + fmt%(float(delta_str[-1]))
        # progress bar
        def update_bar(sum_total,accumulated,t0,current_time, scale=0.5):
            percentage = accumulated/sum_total*100
            nchars = int(percentage*scale)
            bar = "\r["+nchars*"="+">"+(int(100*scale)-nchars)*" "+"]"
            time_info = "Elapsed time: %s"%truncate_secs(current_time - t0)
            print(bar+" %6.2f %%, %5.3f/%4.2fGB %s"%(percentage,
                accumulated/1024**3,sum_total/1024**3,time_info),end="")

        id_list = []
        id_current = []
        id_total = 0
        t0 = prev_time = datetime.datetime.now()
        try:
            # Use a lower level pull call to stream the pull
            for line in self.docker.api.pull(pull_image,stream=True, decode=True):
                if 'progress' not in line:
                    continue
                line_current = line['progressDetail']['current']
                if line['id'] not in id_list:
                    id_list.append(line['id'])
                    id_current.append(line_current)
                    id_total += line['progressDetail']['total']
                else:
                    id_current[id_list.index(line['id'])] = line_current
                current_time = datetime.datetime.now()
                if (current_time-prev_time).total_seconds()<1:
                    # To limit print statements to no more than 1 per second.
                    continue
                prev_time = current_time
                update_bar(id_total,sum(id_current),t0,current_time)
            # Last update of the progress bar:
            update_bar(id_total,sum(id_current),t0,current_time)
        except Exception as e:
            raise RuntimeError("\nException encountered while pulling image {}\nException: {}".format(pull_image,str(e)))

        print() # to avoid erasing the progress bar at the end

        return

    def export_container(self,bucket,tag=None, filename=None):
        '''
        Export existing container to a tared image file.  After tar file has been created, image of container is removed.
        '''

        # TODO:
        # Add checks that image was sucessfully saved before removing it?
        # Pass in repository name - currently hard-coded
        # Repository naming conventions?
        # Does the tag name matter?

        container = self.docker.containers.get(bucket['docker']['container'])

        # create new image from container
        container.commit(repository='earthcubeingeo/resen-lite',tag=tag)

        # save image as *.tar file
        image_name = 'earthcubeingeo/resen-lite:{}'.format(tag)
        image = self.docker.images.get(image_name)
        out = image.save()
        with open(filename, 'wb') as f:
            for chunk in out:
                f.write(chunk)

        # remove image after it has been saved
        self.docker.images.remove(image_name)

        return

    def import_image(self,filename,name=None):
        '''
        Import an image from a tar file.  Return the image ID.
        '''

        # can add tag with image.tag(repository, tag=)
        # Do we want to? Does this matter?
        # Images don't NEED tags, but it makes it convenient

        with open(filename, 'rb') as f:
            image = self.docker.images.load(f)[0]

        return image.id

    def get_container_size(self, bucket):
        # determine the size of the container (disk space)
        # this is usuful for determining if the commit/save is possible or if the image will be too big
        self.apiclient = docker.APIClient()
        # container = self.docker.containers.get(bucket['docker']['container'])
        out = self.apiclient.inspect_container(bucket['docker']['container'])
        print(out.keys())
        # Can't figure out if there is a way to determine the size of the container itself
        # using self.apiclient.inspect_image(), you can determine the size of the base image, but this won't included anything the user's added


    def get_container_status(self, bucket):
        '''
        Get the status of a particular container.
        '''
        container = self.docker.containers.get(bucket['docker']['container'])
        container.reload()  # maybe redundant

        return container.status

    # # get a container object given a container id
    # def get_container(self,container_id):
    #     try:
    #         container = self.docker.containers.get(container_id)
    #         return container
    #     except docker.errors.NotFound:
    #         print("ERROR: No such container: %s" % container_id)
    #         return None
