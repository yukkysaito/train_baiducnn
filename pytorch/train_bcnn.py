from datetime import datetime

import numpy as np
import torch
import torch.optim as optim
import visdom
from NuscData import test_dataloader, train_dataloader
from weighted_mse import wmse
from BCNN import BCNN


def train(epo_num, pretrained_model):
    best_loss = 1e10
    vis = visdom.Visdom()

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    bcnn_model = BCNN().to(device)
    bcnn_model.load_state_dict(torch.load(pretrained_model))
    bcnn_model.eval()

    transfer_learning = False
    if transfer_learning:
        params_to_update = []
        update_param_names = ["deconv0.weight", "deconv0.bias"]
        for name, param in bcnn_model.named_parameters():
            if name in update_param_names:
                param.requires_grad = True
                params_to_update.append(param)
                print(name)
            else:
                param.requires_grad = False
        print("-----------")
        print(params_to_update)
        optimizer = optim.SGD(params=params_to_update, lr=1e-5, momentum=0.9)
    else:
        optimizer = optim.SGD(bcnn_model.parameters(), lr=1e-6, momentum=0.9)

    # optimizer = torch.optim.Adam(bcnn_model.parameters(), lr=1e-6)
    # optimizer = optim.SGD(bcnn_model.parameters(), lr=1e-4)

    # start timing
    prev_time = datetime.now()
    for epo in range(epo_num):
        train_loss = 0
        bcnn_model.train()
        for index, (nusc, nusc_msk) in enumerate(train_dataloader):
            pos_weight = nusc_msk.detach().numpy().copy()
            pos_weight = pos_weight[0]

            zeroidx = np.where(pos_weight == 0)
            nonzeroidx = np.where(pos_weight != 0)
            pos_weight[zeroidx] = 0.25
            pos_weight[nonzeroidx] = 1.
            pos_weight = torch.from_numpy(pos_weight)
            pos_weight = pos_weight.to(device)
            criterion = wmse().to(device)
            nusc = nusc.to(device)
            nusc_msk = nusc_msk.to(device)
            optimizer.zero_grad()
            output = bcnn_model(nusc)
            output = output[:, 0, :, :]
            # output = torch.sigmoid(output)

            loss = criterion(output, nusc_msk, pos_weight)
            loss.backward()
            iter_loss = loss.item()

            train_loss += iter_loss
            optimizer.step()

            output_np = output.cpu().detach().numpy().copy()
            output_np = output_np.transpose(1, 2, 0)
            output_img = np.zeros((640, 640, 1), dtype=np.uint8)
            # conf_idx = np.where(output_np[..., 0] > output_np[..., 0].mean())
            conf_idx = np.where(output_np[..., 0] > 0.5)
            output_img[conf_idx] = 255
            output_img = output_img.transpose(2, 0, 1)
            nusc_msk_img = nusc_msk.cpu().detach().numpy().copy()
            nusc_img = nusc[:, 7, ...].cpu().detach().numpy().copy()
            if np.mod(index, 25) == 0:
                print('epoch {}, {}/{},train loss is {}'.format(
                    epo,
                    index,
                    len(train_dataloader),
                    iter_loss))
                vis.images(nusc_img,
                           win='nusc_img',
                           opts=dict(title='nusc input'))
                vis.images(output_img,
                           win='train_pred',
                           opts=dict(title='train prediction'))
                vis.images(nusc_msk_img,
                           win='train_label',
                           opts=dict(title='train_label'))

        avg_train_loss = train_loss / len(train_dataloader)

        test_loss = 0
        bcnn_model.eval()
        with torch.no_grad():
            for index, (nusc, nusc_msk) in enumerate(test_dataloader):

                nusc = nusc.to(device)
                nusc_msk = nusc_msk.to(device)

                optimizer.zero_grad()
                output = bcnn_model(nusc)
                output = output[:, 0, :, :]
                # output = torch.sigmoid(output)
                loss = criterion(output, nusc_msk, pos_weight)
                iter_loss = loss.item()

                test_loss += iter_loss

                output_np = output.cpu().detach().numpy().copy()
                output_np = output_np.transpose(1, 2, 0)
                output_img = np.zeros((640, 640, 1), dtype=np.uint8)
                # conf_idx = np.where(output_np[..., 0] > output_np[..., 0].mean())
                conf_idx = np.where(output_np[..., 0] > 0.5)
                output_img[conf_idx] = 255
                output_img = output_img.transpose(2, 0, 1)

                nusc_msk_img = nusc_msk.cpu().detach().numpy().copy()
                if np.mod(index, 25) == 0:
                    vis.images(output_img, win='test_pred', opts=dict(
                        title='test prediction'))
                    vis.images(nusc_msk_img,
                               win='test_label', opts=dict(title='test_label'))

            avg_test_loss = test_loss / len(test_dataloader)

        vis.line(X=np.array([epo]), Y=np.array([avg_train_loss]), win='loss',
                 name='avg_train_loss', update='append')
        vis.line(X=np.array([epo]), Y=np.array([avg_test_loss]), win='loss',
                 name='avg_test_loss', update='append')

        cur_time = datetime.now()
        h, remainder = divmod((cur_time - prev_time).seconds, 3600)
        m, s = divmod(remainder, 60)
        time_str = "Time %02d:%02d:%02d" % (h, m, s)
        prev_time = cur_time

        torch.save(bcnn_model.state_dict(),
                   'checkpoints/bcnn_latestmodel_0122.pt')
        print('epoch train loss = %f, epoch test loss = %f, best_loss = %f, %s'
              % (train_loss/len(train_dataloader),
                 test_loss/len(test_dataloader),
                 best_loss,
                 time_str))
        if best_loss > test_loss/len(test_dataloader):
            print('update best model {} -> {}'.format(
                best_loss, test_loss/len(test_dataloader)))
            best_loss = test_loss/len(test_dataloader)
            torch.save(bcnn_model.state_dict(),
                       'checkpoints/bcnn_bestmodel_0122.pt')


if __name__ == "__main__":
    pretrained_model = "checkpoints/bcnn_bestmodel_0111.pt"
    train(epo_num=100000, pretrained_model=pretrained_model)
