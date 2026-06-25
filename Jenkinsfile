pipeline {
    agent any

    environment {
        BACKEND_DOCKER_IMAGE = "webhookmessengerwebhookmessenger"
        BACKEND_DOCKER_NAME = "sexualai-webhookmessenger"
        APP_NETWORK = "sexualai-network"
        DOCKER_TAG = "latest"
        BACKEND_PORT = "5487"
    }

    triggers {
        GenericTrigger(
            genericVariables: [
                [key: 'git_branch', value: '$ref'],
                [key: 'git_commit', value: '$after']
            ],
            token: 'e0qd6yCegUmPzNd96p2f1AdqnRRNaxLynIRAYAHrse8yr5uRaFGwyIoO3qR1yqzdotiSM6FFXtIRCH2KUhJVtHmQubskXUc8scRDQoLchAet6iPdkbAVBbPnJaVRKpvZmo4HN2m5ZTeiPe5GZTBQR0APWMfznPvHfGuFR92bOPVzOy3fuHFfDHKSezUzcgpPj88yir0ijUv0nWAkMct5nV8TVP8xLgy4EuMMWTm5eUiwyvZ8dw9wKJ',
            printContributedVariables: true,
            printPostContent: true
        )
    }

    stages {

        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Build Webhookmessenger Docker Image') {
            steps {
                sh "docker build -t ${BACKEND_DOCKER_IMAGE}:${DOCKER_TAG} -f webhookmessenger/Dockerfile ."
            }
        }

        stage('Deploy Webhookmessenger') {
            steps {
                script {
                    sh "docker network create ${APP_NETWORK} || true"
                    sh "docker stop ${BACKEND_DOCKER_NAME} || true && docker rm ${BACKEND_DOCKER_NAME} || true"

                    sh """
                        docker run -d --name ${BACKEND_DOCKER_NAME} \
                            --env-file .env.build \
                            --network ${APP_NETWORK} \
                            --add-host=host.docker.internal:host-gateway \
                            -p 0.0.0.0:${BACKEND_PORT}:5487 \
                            ${BACKEND_DOCKER_IMAGE}:${DOCKER_TAG}
                    """
                    sh "sleep 10 && curl -f http://127.0.0.1:${BACKEND_PORT}/ || echo '⚠️ Le webhookmessenger ne répond pas encore...'"
                }
            }
        }
    }

    post {
        success {
            echo '✅ Pipeline terminé avec succès.'
            archiveArtifacts artifacts: '*.log', allowEmptyArchive: true
        }
        failure {
            echo '❌ Le pipeline a échoué.'
            archiveArtifacts artifacts: '*.log', allowEmptyArchive: true
        }
    }
}